"""
Wallet Analysis Runner

Jedes beobachtete Wallet bekommt ein eigenes virtuelles Konto (1000 EUR).
Jeder BUY eines Wallets öffnet eine eigene Position  unabhängig von anderen.
Jeder SELL schließt exakt diese Position.
Max. N globale offene Positionen gleichzeitig  Counter geht nach SELL wieder runter.

Sicherheitsmechanismen (identisch zu paper_mainnet):
  - ConnectionHealthMonitor: Emergency Exit bei Netzwerkausfall
  - Reconnect Callback: Verpasste SELLs nach Reconnect prüfen
  - PriceMonitor: Stop-Loss / Take-Profit / 5x kein Preis  Totalverlust
  - Shutdown: aktueller Marktpreis, bei fehlendem Preis  Totalverlust

Realitätsnähe hat immer Priorität.
"""

import asyncio
import aiohttp
import signal
import sys
import logging
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass, field

from config.network import RPC_HTTP_ENDPOINTS, NETWORK_MAINNET
from wallets.sync import sync_wallets
from observation.sources.solana_polling import SolanaPollingSource
from observation.models import TradeEvent
from trading.price_oracle import PriceOracle
from trading.wallet_tracker import WalletTracker
from trading.connection_monitor import ConnectionHealthMonitor

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

CAPITAL_PER_WALLET_EUR = 1000.0
POSITION_SIZE_PERCENT  = 0.20
MAX_PRICE_FAILURES     = 5


@dataclass
class WalletPosition:
    wallet:          str
    token:           str
    entry_price_eur: float
    amount:          float
    cost_eur:        float
    entry_time:      datetime


@dataclass
class WalletAccount:
    wallet:  str
    capital: float = CAPITAL_PER_WALLET_EUR
    cash:    float = field(init=False)

    positions:     Dict[str, WalletPosition] = field(default_factory=dict)
    closed_trades: list                       = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.capital

    @property
    def total_pnl_eur(self) -> float:
        return sum(t['pnl_eur'] for t in self.closed_trades if t['pnl_eur'] is not None)

    @property
    def win_rate(self) -> float:
        sells = [t for t in self.closed_trades if t['side'] == 'SELL']
        if not sells:
            return 0.0
        return len([t for t in sells if (t['pnl_eur'] or 0) > 0]) / len(sells)

    @property
    def num_trades(self) -> int:
        return len([t for t in self.closed_trades if t['side'] == 'SELL'])

    def open_position(self, token: str, price_eur: float) -> Optional[WalletPosition]:
        if token in self.positions or price_eur <= 0:
            return None
        invest = self.cash * POSITION_SIZE_PERCENT
        if invest < 0.01:
            return None
        amount = invest / price_eur
        pos = WalletPosition(
            wallet=self.wallet, token=token,
            entry_price_eur=price_eur, amount=amount,
            cost_eur=invest, entry_time=datetime.now()
        )
        self.positions[token] = pos
        self.cash -= invest
        self.closed_trades.append({
            'side': 'BUY', 'token': token,
            'price_eur': price_eur, 'amount': amount,
            'value_eur': invest, 'pnl_eur': None,
            'price_missing': False,
            'timestamp': datetime.now().isoformat()
        })
        return pos

    def close_position(self, token: str, price_eur: float, price_missing: bool = False) -> Optional[dict]:
        pos = self.positions.pop(token, None)
        if pos is None:
            return None
        sell_value = pos.amount * price_eur
        pnl_eur    = (price_eur - pos.entry_price_eur) * pos.amount
        pnl_pct    = ((price_eur - pos.entry_price_eur) / pos.entry_price_eur * 100) if pos.entry_price_eur > 0 else 0
        self.cash += sell_value
        record = {
            'side': 'SELL', 'token': token,
            'price_eur': price_eur, 'amount': pos.amount,
            'value_eur': sell_value, 'pnl_eur': pnl_eur,
            'pnl_percent': pnl_pct, 'entry_price_eur': pos.entry_price_eur,
            'price_missing': price_missing,
            'timestamp': datetime.now().isoformat()
        }
        self.closed_trades.append(record)
        return record


class WalletAnalysisRunner:

    PRICE_UPDATE_INTERVAL = 10
    STOP_LOSS_PERCENT     = -50.0
    TAKE_PROFIT_PERCENT   = 100.0

    def __init__(self):
        self.shutting_down  = False
        self.source:             Optional[SolanaPollingSource]    = None
        self.oracle:             Optional[PriceOracle]            = None
        self.tracker:            Optional[WalletTracker]          = None
        self.connection_monitor: Optional[ConnectionHealthMonitor] = None

        self.accounts: Dict[str, WalletAccount] = {}

        self.max_positions: int = 1
        # token  (account, last_price)
        self.open_positions:    Dict[str, tuple] = {}
        self.price_fail_counts: Dict[str, int]   = {}

        # Inaktivitäts-Tracking: token  (letzter_preis, monotonic_time)
        self.inactivity_tracker: Dict[str, tuple] = {}

        self.active_token:   Optional[str]           = None
        self.active_account: Optional[WalletAccount] = None
        self.last_price:     float                   = 0.0

        self.price_update_task: Optional[asyncio.Task] = None

        self.session_id = datetime.now().strftime("analysis_%Y%m%d_%H%M%S")
        self.start_time: Optional[datetime] = None

        self.total_buys  = 0
        self.total_sells = 0

    # 
    # STARTUP
    # 

    async def run(self):
        print()
        print("="*70)
        print(" WALLET ANALYSIS MODE")
        print("   Jedes Wallet hat ein eigenes Konto (1000 EUR, 20% pro Trade)")
        print(f"   Stop-Loss: {self.STOP_LOSS_PERCENT:.0f}%  |  Take-Profit: +{self.TAKE_PROFIT_PERCENT:.0f}%")
        print(f"   Preis-Ausfall: Totalverlust nach {MAX_PRICE_FAILURES} fehlgeschlagenen Abfragen")
        print("="*70)
        print()

        active_wallets = sync_wallets()
        if not active_wallets:
            logger.error(" No active wallets found!")
            return

        wallet_addresses = [w.wallet for w in active_wallets]
        logger.info(f"[Wallets] Loaded {len(wallet_addresses)} wallets")

        for w in wallet_addresses:
            self.accounts[w] = WalletAccount(wallet=w)

        self.oracle  = PriceOracle()
        self.tracker = WalletTracker()

        conf_map = self.tracker.get_confidence_map(wallet_addresses)
        known = [(w, s) for w, s in conf_map.items() if s != 0.5]
        if known:
            print(f" Bekannte Wallet Scores ({len(known)}/{len(wallet_addresses)}):")
            for w, s in sorted(known, key=lambda x: -x[1])[:10]:
                print(f"   {w[:20]}...  {s:.2f}")
            print()

        # Config vor Source/Monitor damit failure_threshold bekannt ist
        self._get_config_from_user()

        self.connection_monitor = ConnectionHealthMonitor(
            emergency_callback=self._emergency_close_all_positions,
            reconnect_callback=self._check_for_missed_sells,
            failure_threshold_seconds=self.config['failure_threshold'],
            check_interval=5.0
        )

        self.source = SolanaPollingSource(
            rpc_http_url=RPC_HTTP_ENDPOINTS[NETWORK_MAINNET],
            wallets=wallet_addresses,
            callback=self._handle_trade,
            poll_interval=5,
            fast_poll_interval=0.5,
            connection_monitor=self.connection_monitor
        )

        signal.signal(signal.SIGINT, self._signal_handler)
        self.start_time = datetime.now()

        print(" Watching all wallets...")
        print("   Press CTRL+C to stop and see results")
        print()

        try:
            await self.source.connect()
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    def _get_config_from_user(self):
        self.config = {}
        print()
        print("="*70)
        print("  ANALYSIS CONFIGURATION")
        print("="*70)
        print()
        print("Drücke ENTER für Standardwerte")
        print()

        while True:
            inp = input(" Max. gleichzeitige Positionen [1]: ").strip()
            if not inp:
                self.max_positions = 1
                break
            try:
                v = int(inp)
                if v < 1:
                    print("    Muss mindestens 1 sein!")
                    continue
                self.max_positions = v
                break
            except ValueError:
                print("    Bitte eine ganze Zahl eingeben!")

        while True:
            inp = input("  Connection Timeout (Sekunden) [30]: ").strip()
            if not inp:
                self.config['failure_threshold'] = 30
                break
            try:
                v = int(inp)
                if v <= 0:
                    print("    Muss größer als 0 sein!")
                    continue
                self.config['failure_threshold'] = v
                break
            except ValueError:
                print("    Bitte eine ganze Zahl eingeben!")

        print()
        print("="*70)
        print(f"   Modus:              {'1 globale Position' if self.max_positions == 1 else f'bis zu {self.max_positions} gleichzeitige Positionen'}")
        print(f"   Kapital pro Wallet: {CAPITAL_PER_WALLET_EUR:.0f} EUR (je {POSITION_SIZE_PERCENT*100:.0f}% = {CAPITAL_PER_WALLET_EUR * POSITION_SIZE_PERCENT:.0f} EUR pro Trade)")
        print(f"   Stop-Loss:          {self.STOP_LOSS_PERCENT:.0f}%")
        print(f"   Take-Profit:        +{self.TAKE_PROFIT_PERCENT:.0f}%")
        print(f"   Preis-Ausfall:      Totalverlust nach {MAX_PRICE_FAILURES}x kein Preis")
        print(f"   Connection Timeout: {self.config['failure_threshold']}s")
        print("="*70)
        print()

    # 
    # EMERGENCY EXIT (Connection Lost)
    # 

    async def _emergency_close_all_positions(self):
        """ Netzwerkausfall  alle Positionen sofort schließen"""
        print()
        print("="*70)
        print(" EMERGENCY: CONNECTION LOST  CLOSING ALL POSITIONS!")
        print("="*70)

        if not self.open_positions:
            print("   No open positions to close.")
            return

        for token, (account, last_price) in list(self.open_positions.items()):
            # Letzten bekannten Preis verwenden  realistischer als 0
            # (Verbindung war kurz weg, Preis vor Ausfall ist beste Näherung)
            print(f"    Force closed {token[:8]}... @ {last_price:.8f} EUR (last known price)")
            await self._close_position(
                token=token,
                account=account,
                price_eur=last_price,
                reason="EMERGENCY_EXIT_CONNECTION_LOST",
                trigger_label="Connection lost"
            )

        print(f" Emergency exit completed")
        print("="*70)
        print()

    # 
    # RECONNECT  Verpasste SELLs prüfen
    # 

    async def _check_for_missed_sells(self):
        """ Nach Reconnect: Prüft ob Wallets während Offline-Phase verkauft haben"""
        if not self.open_positions:
            return

        logger.info("[MissedSells] Checking for missed SELLs during offline period...")
        missed = 0

        for token, (account, _) in list(self.open_positions.items()):
            wallet = account.wallet
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "jsonrpc": "2.0", "id": 1,
                        "method": "getSignaturesForAddress",
                        "params": [wallet, {"limit": 10}]
                    }
                    async with session.post(
                        self.source.rpc_http_url, json=payload,
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        data = await resp.json()
                        if "error" in data:
                            continue

                        for sig_info in data.get("result", [])[:5]:
                            sig = sig_info.get("signature")
                            tx_payload = {
                                "jsonrpc": "2.0", "id": 1,
                                "method": "getTransaction",
                                "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                            }
                            async with session.post(
                                self.source.rpc_http_url, json=tx_payload,
                                timeout=aiohttp.ClientTimeout(total=5)
                            ) as tx_resp:
                                tx_data = await tx_resp.json()
                                if "error" in tx_data:
                                    continue
                                tx = tx_data.get("result")
                                if not tx:
                                    continue

                                trade_event = self.source.extract_trade(tx, wallet, sig)
                                if trade_event and trade_event.token == token and trade_event.side == "SELL":
                                    missed += 1
                                    price = await self.oracle.get_price_eur(token)
                                    exit_price = price if price else 0.0
                                    price_missing = price is None
                                    if price_missing:
                                        logger.warning(f"[MissedSells] No price for {token[:8]}...  using 0 EUR")
                                    await self._close_position(
                                        token=token,
                                        account=account,
                                        price_eur=exit_price,
                                        reason="MISSED_SELL_DETECTED_ON_RECONNECT",
                                        trigger_label=f"{wallet[:8]}... sold (missed)",
                                        price_missing=price_missing
                                    )
                                    break

            except Exception as e:
                logger.error(f"[MissedSells] Error checking {wallet[:8]}: {e}")
                continue

        if missed > 0:
            logger.info(f"[MissedSells]  Found and processed {missed} missed SELL(s)")
        else:
            logger.info("[MissedSells]  No missed SELLs detected")

    # 
    # TRADE HANDLER
    # 

    async def _handle_trade(self, trade: TradeEvent):
        account = self.accounts.get(trade.wallet)
        if account is None:
            return

        in_fast_mode = (
            self.source and
            hasattr(self.source, 'is_fast_polling') and
            self.source.is_fast_polling
        )
        if not in_fast_mode or trade.token in self.open_positions:
            logger.info(
                f" [analysis] {trade.wallet[:8]}... "
                f"{trade.side:4} {trade.amount:>12.2f} {trade.token[:8]}..."
            )

        if trade.side == "BUY":
            await self._handle_buy(account, trade.token)
        elif trade.side == "SELL":
            await self._handle_sell(account, trade.token)

    async def _handle_buy(self, account: WalletAccount, token: str):
        if len(self.open_positions) >= self.max_positions:
            return
        if token in self.open_positions:
            return

        price_eur = await self.oracle.get_price_eur(token)
        if not price_eur:
            logger.warning(f"[analysis]   BUY skipped  no price for {token[:8]}...")
            return

        pos = account.open_position(token, price_eur)
        if not pos:
            return

        self.open_positions[token]    = (account, price_eur)
        self.price_fail_counts[token] = 0
        self.total_buys += 1

        # Inaktivitäts-Timer starten
        import time
        self.inactivity_tracker[token] = (price_eur, time.monotonic())

        self.active_token   = token
        self.active_account = account
        self.last_price     = price_eur

        self.tracker.record_buy(
            session_id=self.session_id,
            wallet=account.wallet,
            token=token,
            amount=pos.amount,
            price_eur=price_eur
        )

        open_slots = f"{len(self.open_positions)}/{self.max_positions}"
        print()
        print("="*70)
        print(" BUY SIGNAL DETECTED!")
        print("="*70)
        print(f"Token:        {token[:20]}...")
        print(f"Wallet:       {account.wallet[:20]}...")
        print(f"Entry Price:  {price_eur:.8f} EUR")
        print(f"Invested:     {pos.cost_eur:.2f} EUR")
        print(f"Amount:       {pos.amount:.4f}")
        print(f"Slots:        {open_slots}")
        print("="*70)
        print()

        logger.info(
            f"[Portfolio]  BOUGHT {pos.amount:.4f} {token[:8]}... "
            f"@ {price_eur:.8f} EUR = {pos.cost_eur:.2f} EUR"
        )

        if self.price_update_task is None or self.price_update_task.done():
            self.price_update_task = asyncio.create_task(self._price_update_loop())

    async def _handle_sell(self, account: WalletAccount, token: str):
        entry = self.open_positions.get(token)
        if entry is None:
            return
        owning_account, _ = entry
        if owning_account != account:
            return

        price_eur = await self.oracle.get_price_eur(token, skip_cache=True)
        price_missing = price_eur is None
        if price_missing:
            logger.warning(f"[analysis]   SELL  no price for {token[:8]}..., assuming total loss (0 EUR)")
            price_eur = 0.0

        await self._close_position(
            token=token,
            account=account,
            price_eur=price_eur,
            reason="WALLET_SOLD",
            trigger_label=f"{account.wallet[:8]}... sold",
            price_missing=price_missing
        )

    # 
    # POSITION SCHLIESSEN (zentral)
    # 

    async def _close_position(
        self,
        token: str,
        account: WalletAccount,
        price_eur: float,
        reason: str,
        trigger_label: str,
        price_missing: bool = False
    ):
        record = account.close_position(token, price_eur, price_missing=price_missing)
        if not record:
            return

        self.open_positions.pop(token, None)
        self.price_fail_counts.pop(token, None)
        self.inactivity_tracker.pop(token, None)
        self.total_sells += 1

        # Tag-Abbau: nur wenn Close NICHT durch Inaktivität ausgelöst wurde
        if reason != "INACTIVITY":
            current_tags = self.tracker.get_inactivity_tags(account.wallet)
            if current_tags > 0:
                self.tracker.remove_inactivity_tag(account.wallet)

        pnl_eur      = record['pnl_eur']
        pnl_pct      = record['pnl_percent']
        result_emoji = "" if pnl_eur >= 0 else ""
        missing_tag  = "    [PREIS NICHT VERFÜGBAR  TOTALVERLUST ANGENOMMEN]" if price_missing else ""
        open_slots   = f"{len(self.open_positions)}/{self.max_positions}"

        print()
        print("="*70)
        print(f"{result_emoji} SELL SIGNAL DETECTED! [{reason}]{missing_tag}")
        print("="*70)
        print(f"Token:        {token[:20]}...")
        print(f"Trigger:      {trigger_label}")
        print(f"Wallet:       {account.wallet[:20]}...")
        print(f"Entry Price:  {record['entry_price_eur']:.8f} EUR")
        print(f"Exit Price:   {price_eur:.8f} EUR" + ("   (kein Preis abrufbar)" if price_missing else ""))
        print(f"P&L:          {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%)")
        print(f"Amount:       {record['amount']:.4f}")
        print(f"Slots:        {open_slots}")
        if price_missing:
            print(f"  HINWEIS: Kein Preis abrufbar  Trade in DB als 'price_missing' markiert.")
        print("="*70)
        print()

        logger.info(
            f"[PaperPortfolio] {'' if pnl_eur >= 0 else ''} SOLD {record['amount']:.4f} "
            f"{token[:8]}... @ {price_eur:.8f} EUR = {record['value_eur']:.2f} EUR"
            + ("   price_missing" if price_missing else "")
        )
        logger.info(f"[PaperPortfolio] P&L: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%)")

        self.tracker.record_sell(
            session_id=self.session_id,
            wallet=account.wallet,
            token=token,
            amount=record['amount'],
            price_eur=price_eur,
            entry_price_eur=record['entry_price_eur'],
            price_missing=price_missing
        )

        if self.open_positions:
            next_token, (next_account, next_price) = next(iter(self.open_positions.items()))
            self.active_token   = next_token
            self.active_account = next_account
            self.last_price     = next_price
        else:
            self.active_token   = None
            self.active_account = None
            self.last_price     = 0.0
            if self.price_update_task and not self.price_update_task.done():
                self.price_update_task.cancel()

    # 
    # PRICE MONITOR LOOP
    # 

    async def _price_update_loop(self):
        logger.info(
            f"[PriceMonitor] Started (updates every {self.PRICE_UPDATE_INTERVAL}s | "
            f"SL: {self.STOP_LOSS_PERCENT:.0f}% | TP: +{self.TAKE_PROFIT_PERCENT:.0f}% | "
            f"Max price failures: {MAX_PRICE_FAILURES})"
        )
        try:
            while True:
                await asyncio.sleep(self.PRICE_UPDATE_INTERVAL)

                if not self.open_positions:
                    break

                for token, (account, _) in list(self.open_positions.items()):
                    pos = account.positions.get(token)
                    if pos is None:
                        continue

                    current_price = await self.oracle.get_price_eur(token, skip_cache=True)

                    if current_price is None:
                        self.price_fail_counts[token] = self.price_fail_counts.get(token, 0) + 1
                        fails = self.price_fail_counts[token]
                        logger.warning(
                            f"[PriceMonitor]   No price for {token[:8]}... "
                            f"({fails}/{MAX_PRICE_FAILURES} failures)"
                        )
                        if fails >= MAX_PRICE_FAILURES:
                            logger.warning(
                                f"[PriceMonitor]  {token[:8]}...  {MAX_PRICE_FAILURES}x no price. "
                                f"Assuming total loss (0 EUR)."
                            )
                            await self._close_position(
                                token=token, account=account,
                                price_eur=0.0,
                                reason="PRICE_UNAVAILABLE",
                                trigger_label=f"{MAX_PRICE_FAILURES}x kein Preis abrufbar",
                                price_missing=True
                            )
                        continue

                    self.price_fail_counts[token] = 0

                    entry_price = pos.entry_price_eur
                    pnl_eur     = (current_price - entry_price) * pos.amount
                    pnl_pct     = ((current_price - entry_price) / entry_price) * 100
                    last_price  = self.open_positions[token][1]
                    change_pct  = ((current_price - last_price) / last_price * 100) if last_price > 0 else 0

                    self.open_positions[token] = (account, current_price)

                    #  Inaktivitäts-Tracking 
                    import time
                    last_changed_price, last_changed_time = self.inactivity_tracker.get(
                        token, (current_price, time.monotonic())
                    )
                    if current_price != last_changed_price:
                        self.inactivity_tracker[token] = (current_price, time.monotonic())
                        last_changed_time = time.monotonic()

                    timeout = self.tracker.get_inactivity_timeout([account.wallet])
                    inactive_secs = time.monotonic() - last_changed_time

                    emoji = "" if pnl_eur > 0 else "" if pnl_eur < 0 else ""
                    print(
                        f"{emoji} [PriceMonitor] {token[:8]}... @ {current_price:.8f} EUR "
                        f"| P&L: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%) "
                        f"| Last {self.PRICE_UPDATE_INTERVAL}s: {change_pct:+.2f}%"
                        + (f" | Inaktiv: {inactive_secs/60:.1f}/{timeout//60} Min" if inactive_secs > 30 else "")
                    )

                    if inactive_secs >= timeout:
                        logger.warning(
                            f"[Inactivity]  {token[:8]}... no price change for "
                            f"{inactive_secs/60:.1f} min (limit {timeout//60} min)  closing"
                        )
                        tags = self.tracker.add_inactivity_tag(account.wallet)
                        logger.info(f"[Inactivity] Tag {account.wallet[:8]}...  {tags}/3")
                        await self._close_position(
                            token=token, account=account,
                            price_eur=current_price,
                            reason="INACTIVITY",
                            trigger_label=f"Inaktiv {inactive_secs/60:.1f} min (limit {timeout//60} min)"
                        )
                        continue

                    if pnl_pct <= self.STOP_LOSS_PERCENT:
                        logger.warning(
                            f"[StopLoss]  {token[:8]}... hit stop-loss "
                            f"({pnl_pct:.1f}% <= {self.STOP_LOSS_PERCENT:.0f}%)"
                        )
                        await self._close_position(
                            token=token, account=account,
                            price_eur=current_price,
                            reason="STOP_LOSS",
                            trigger_label=f"Stop-Loss @ {pnl_pct:.1f}%"
                        )
                        continue

                    if pnl_pct >= self.TAKE_PROFIT_PERCENT:
                        logger.info(
                            f"[TakeProfit]  {token[:8]}... hit take-profit "
                            f"({pnl_pct:.1f}% >= +{self.TAKE_PROFIT_PERCENT:.0f}%)"
                        )
                        await self._close_position(
                            token=token, account=account,
                            price_eur=current_price,
                            reason="TAKE_PROFIT",
                            trigger_label=f"Take-Profit @ +{pnl_pct:.1f}%"
                        )

        except asyncio.CancelledError:
            logger.info("[PriceMonitor] Stopped")
        except Exception as e:
            logger.error(f"[PriceMonitor] Crashed: {e}")

    # 
    # SIGNAL HANDLER & SHUTDOWN
    # 

    def _signal_handler(self, signum, frame):
        if self.shutting_down:
            return
        print("\n\n Stopping analysis...")
        self.shutting_down = True
        if self.source:
            self.source.stop()

    async def _shutdown(self):
        if hasattr(self, '_shutdown_called') and self._shutdown_called:
            return
        self._shutdown_called = True

        if self.price_update_task and not self.price_update_task.done():
            self.price_update_task.cancel()

        if self.connection_monitor:
            self.connection_monitor.stop()

        if self.open_positions:
            print(f"\n Closing {len(self.open_positions)} open position(s) at current market price...")
            for token, (account, _) in list(self.open_positions.items()):
                price = await self.oracle.get_price_eur(token, skip_cache=True)
                price_missing = price is None
                if price_missing:
                    price = 0.0
                    logger.warning(f"[Shutdown]   No price for {token[:8]}...  assuming total loss (0 EUR)")
                await self._close_position(
                    token=token, account=account,
                    price_eur=price,
                    reason="SESSION_ENDED",
                    trigger_label="Session ended",
                    price_missing=price_missing
                )

        runtime_str = ""
        if self.start_time:
            rt = datetime.now() - self.start_time
            h  = int(rt.total_seconds() // 3600)
            m  = int((rt.total_seconds() % 3600) // 60)
            s  = int(rt.total_seconds() % 60)
            runtime_str = f"{h}h {m}m {s}s"

        active_accounts = [a for a in self.accounts.values() if a.num_trades > 0]

        print()
        print("="*70)
        print(f" WALLET ANALYSIS RESULTS  |  Runtime: {runtime_str}")
        print(f"   Session: {self.session_id}")
        print("="*70)

        if not active_accounts:
            print("   No trades observed in this session.")
        else:
            sorted_accounts = sorted(active_accounts, key=lambda a: a.total_pnl_eur, reverse=True)

            # Spaltenbreiten Wallet-Übersicht
            # Marker(1) + Wallet(47) + Trades(6) + Win%(6) + P&L EUR(12) + Confidence(10) + Strategy(12)
            print(f"  {'':1}  {'Wallet':<47} {'Trades':>6} {'Win%':>6} {'P&L EUR':>12} {'Conf':>6} {'Strategy':<12}")
            print("  " + "-"*98)

            for acc in sorted_accounts:
                conf   = self.tracker.get_confidence(acc.wallet)
                label  = self.tracker.get_strategy_label(acc.wallet)
                pnl_str = f"{acc.total_pnl_eur:+.2f} EUR"
                wr_str  = f"{acc.win_rate*100:.0f}%"
                marker  = "+" if acc.total_pnl_eur > 0 else "-" if acc.total_pnl_eur < 0 else " "
                wallet  = f"{acc.wallet[:44]}..."
                sl, tp  = self.tracker.get_sl_tp_for_wallet(acc.wallet)
                label_str = f"{label}"
                if label != 'UNKNOWN':
                    label_str += f" ({sl:.0f}/{tp:.0f})"
                print(
                    f"  {marker}  {wallet:<47}"
                    f" {acc.num_trades:>5}x"
                    f" {wr_str:>6}"
                    f" {pnl_str:>12}"
                    f" {conf:>6.2f}"
                    f" {label_str:<12}"
                )

            total_pnl = sum(a.total_pnl_eur for a in active_accounts)
            print("  " + "-"*98)
            print(f"     {'TOTAL':<47} {'':>6} {'':>6} {f'{total_pnl:+.2f} EUR':>12}")

            print()
            print("="*70)
            print(" TRADE DETAILS PER WALLET")
            print("="*70)

            # Spaltenbreiten Trade-Details
            # res(2) + 2sp + Token(12) + Entry EUR(14) + Exit EUR(14) + P&L EUR(11) + P&L%(8) + Flag
            trade_header  = f"  {'':2}  {'Token':<12} {'Entry EUR':>14} {'Exit EUR':>14} {'P&L EUR':>11} {'P&L%':>8}  Flag"
            trade_divider = "  " + "-"*69

            for acc in sorted_accounts:
                sells = [t for t in acc.closed_trades if t['side'] == 'SELL']
                if not sells:
                    continue
                conf = self.tracker.get_confidence(acc.wallet)
                print(f"\n  Wallet: {acc.wallet[:44]}...  confidence: {conf:.2f}")
                print(trade_header)
                print(trade_divider)
                for t in sells:
                    result = "OK" if (t['pnl_eur'] or 0) >= 0 else "--"
                    flag   = " [price_missing]" if t.get('price_missing') else ""
                    print(
                        f"  {result}  {t['token'][:12]:<12}"
                        f" {t.get('entry_price_eur', 0):>14.8f}"
                        f" {t['price_eur']:>14.8f}"
                        f" {t['pnl_eur']:>+11.2f}"
                        f" {t.get('pnl_percent', 0):>+7.1f}%"
                        f"{flag}"
                    )

        print()
        print("-"*70)
        print(f" Session Statistics:")
        print(f"   Total BUYs:      {self.total_buys}")
        print(f"   Total SELLs:     {self.total_sells}")
        print(f"   Wallets active:  {len(active_accounts)}/{len(self.accounts)}")
        print()

        if self.connection_monitor:
            status = self.connection_monitor.get_status()
            print(f"  Connection Health:")
            print(f"   Final Status:         {'Connected' if status['connected'] else 'Disconnected'}")
            print(f"   Total Disconnections: {status['total_disconnections']}")
            if status['emergency_triggered']:
                print(f"     Emergency Exit was triggered!")
            print()

        print(f" Performance saved to: data/wallet_performance.db")
        print("="*70)

        if self.oracle:
            await self.oracle.close()


async def main():
    runner = WalletAnalysisRunner()
    await runner.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
