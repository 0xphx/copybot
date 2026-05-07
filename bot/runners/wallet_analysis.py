"""
Wallet Analysis Runner

Zwei Modi:

[1] ANALYSIS MODE
    Eigener SL/TP, misst Bot-Performance.
    SL/TP aus Observer-DB abgeleitet (wenn vorhanden).
    Transaktionskosten (cost_model.py) werden berechnet und
    als effective_pnl separat gespeichert.
    Zeigt: raw PnL + effective PnL nach Kosten.

[2] OBSERVER MODE
    Folgt Wallet 1:1, kein SL/TP.
    Timeouts: Stagnation (15 Min) + Max-Haltedauer (60 Min).
    Anti-Softlock: Totalverlust nach 10x kein Preis / 30 Min ohne Preis.
"""

import asyncio
import aiohttp
import signal
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, field

from config.network import (
    RPC_HTTP_ENDPOINTS, WS_ENDPOINTS, WS_HTTP_ENDPOINTS, NETWORK_MAINNET, HELIUS_API_KEYS
)
from wallets.sync import sync_wallets
from observation.sources.solana_polling import SolanaPollingSource
from observation.sources.solana_ws_source import SolanaWebSocketSource
from observation.sources.solana_parallel_source import SolanaParallelSource
from observation.models import TradeEvent
from trading.price_oracle import PriceOracle
from trading.wallet_tracker import WalletTracker
from trading.cost_model import TransactionCostModel, DEFAULT_COST_MODEL
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
    entry_price_eur: float      # Spot-Preis bei Kauf
    entry_price_eff: float      # Effektiver Preis nach Kosten
    amount:          float
    cost_eur:        float      # Position in EUR
    entry_cost_eur:  float      # Transaktionskosten BUY
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
    def total_effective_pnl_eur(self) -> float:
        return sum(t.get('effective_pnl_eur') or t['pnl_eur'] or 0
                   for t in self.closed_trades if t['side'] == 'SELL')

    @property
    def win_rate(self) -> float:
        sells = [t for t in self.closed_trades if t['side'] == 'SELL']
        if not sells:
            return 0.0
        return len([t for t in sells if (t['pnl_eur'] or 0) > 0]) / len(sells)

    @property
    def num_trades(self) -> int:
        return len([t for t in self.closed_trades if t['side'] == 'SELL'])

    def open_position(self, token: str, price_eur: float,
                      observer_mode: bool = False,
                      cost_model: Optional[TransactionCostModel] = None
                      ) -> Optional[WalletPosition]:
        if token in self.positions or price_eur <= 0:
            return None
        if observer_mode:
            invest = CAPITAL_PER_WALLET_EUR * POSITION_SIZE_PERCENT
        else:
            invest = self.cash * POSITION_SIZE_PERCENT
            if invest < 0.01:
                return None

        # Transaktionskosten BUY
        entry_cost_eur = 0.0
        entry_price_eff = price_eur
        if cost_model and not observer_mode:
            entry_price_eff, buy_cost = cost_model.effective_buy_price(price_eur, invest)
            entry_cost_eur = buy_cost.total_cost_eur

        amount = invest / price_eur  # Amount basiert auf Spot-Preis
        pos = WalletPosition(
            wallet=self.wallet, token=token,
            entry_price_eur=price_eur,
            entry_price_eff=entry_price_eff,
            amount=amount, cost_eur=invest,
            entry_cost_eur=entry_cost_eur,
            entry_time=datetime.now()
        )
        self.positions[token] = pos
        self.cash -= invest
        self.closed_trades.append({
            'side': 'BUY', 'token': token,
            'price_eur': price_eur,
            'entry_price_eff': entry_price_eff,
            'amount': amount,
            'value_eur': invest,
            'entry_cost_eur': entry_cost_eur,
            'pnl_eur': None,
            'effective_pnl_eur': None,
            'price_missing': False,
            'timestamp': datetime.now().isoformat()
        })
        return pos

    def close_position(self, token: str, price_eur: float,
                       price_missing: bool = False,
                       cost_model: Optional[TransactionCostModel] = None
                       ) -> Optional[dict]:
        pos = self.positions.pop(token, None)
        if pos is None:
            return None

        # Transaktionskosten SELL
        sell_cost_eur = 0.0
        exit_price_eff = price_eur
        if cost_model and not price_missing:
            exit_price_eff, sell_cost = cost_model.effective_sell_price(price_eur, pos.cost_eur)
            sell_cost_eur = sell_cost.total_cost_eur

        sell_value = pos.amount * price_eur
        pnl_eur    = (price_eur - pos.entry_price_eur) * pos.amount
        pnl_pct    = ((price_eur - pos.entry_price_eur) / pos.entry_price_eur * 100) if pos.entry_price_eur > 0 else 0

        # Effektiver PnL nach allen Kosten
        total_cost       = pos.entry_cost_eur + sell_cost_eur
        effective_pnl    = pnl_eur - total_cost
        effective_pnl_pct = (effective_pnl / pos.cost_eur * 100) if pos.cost_eur > 0 else 0

        self.cash += sell_value
        record = {
            'side': 'SELL', 'token': token,
            'price_eur': price_eur,
            'exit_price_eff': exit_price_eff,
            'amount': pos.amount,
            'value_eur': sell_value,
            'pnl_eur': pnl_eur,
            'pnl_percent': pnl_pct,
            'entry_price_eur': pos.entry_price_eur,
            'entry_price_eff': pos.entry_price_eff,
            'entry_cost_eur': pos.entry_cost_eur,
            'sell_cost_eur': sell_cost_eur,
            'total_cost_eur': total_cost,
            'effective_pnl_eur': effective_pnl,
            'effective_pnl_pct': effective_pnl_pct,
            'price_missing': price_missing,
            'timestamp': datetime.now().isoformat()
        }
        self.closed_trades.append(record)
        return record


class WalletAnalysisRunner:

    PRICE_UPDATE_INTERVAL_NORMAL      = 10
    PRICE_UPDATE_INTERVAL_FAST        = 1
    STOP_LOSS_PERCENT                 = -50.0
    TAKE_PROFIT_PERCENT               = 100.0

    OBSERVER_MAX_PRICE_FAILURES       = 10
    OBSERVER_MAX_NO_PRICE_MINUTES     = 30
    OBSERVER_MAX_HOLD_MINUTES_DEFAULT = 60
    OBSERVER_STAGNATION_MINUTES       = 15

    def __init__(self):
        self.shutting_down      = False
        self.observer_mode      = False
        self.use_websocket      = False
        self.use_parallel       = False
        self.num_parallel_keys  = 2
        self.source             = None
        self.oracle:             Optional[PriceOracle]            = None
        self.tracker:            Optional[WalletTracker]          = None
        self.connection_monitor: Optional[ConnectionHealthMonitor] = None
        self.cost_model:         Optional[TransactionCostModel]   = None

        self.accounts: Dict[str, WalletAccount] = {}

        self.max_positions    = 1
        self.open_positions:  Dict[tuple, tuple] = {}
        self.price_fail_counts: Dict[tuple, int] = {}
        self.inactivity_tracker: Dict[tuple, tuple] = {}
        self.price_extremes:  Dict[tuple, tuple] = {}
        self.observer_last_price_time: Dict[tuple, float] = {}
        self.observer_entry_time: Dict[tuple, float] = {}
        self.observer_stagnation_tracker: Dict[tuple, tuple] = {}
        self.observer_max_hold_minutes = self.OBSERVER_MAX_HOLD_MINUTES_DEFAULT

        # Stores entry_cost_eur per position key for record_sell
        self._entry_costs: Dict[tuple, float] = {}

        self.active_token:   Optional[str]           = None
        self.active_account: Optional[WalletAccount] = None
        self.last_price:     float                   = 0.0
        self.price_update_task: Optional[asyncio.Task] = None

        self.session_id = datetime.now().strftime("analysis_%Y%m%d_%H%M%S")
        self.start_time: Optional[datetime] = None
        self.total_buys  = 0
        self.total_sells = 0

    # ──────────────────────────────────────────────────────────────────
    # STARTUP
    # ──────────────────────────────────────────────────────────────────

    async def run(self):
        self.oracle = PriceOracle()
        print()
        print("="*70)
        print(" WALLET ANALYSIS / OBSERVER")
        print("="*70)
        print()

        self._get_config_from_user()

        num_keys = self.num_parallel_keys if self.use_parallel else 1
        active_wallets = sync_wallets(num_parallel_keys=num_keys)
        if not active_wallets:
            logger.error(" No active wallets found!")
            return

        wallet_addresses = [w.wallet for w in active_wallets]
        print(f" {len(wallet_addresses)} Wallets geladen")
        print()

        db_path  = "data/observer_performance.db" if self.observer_mode else "data/wallet_performance.db"
        obs_path = "data/observer_performance.db" if not self.observer_mode else None
        self.tracker = WalletTracker(
            db_path=db_path,
            observer_mode=self.observer_mode,
            observer_db_path=obs_path,
        )

        # Cost Model nur im Analysis-Modus
        if not self.observer_mode:
            self.cost_model = TransactionCostModel()
            print(f" Transaction Cost Model aktiv:")
            print(f"   Pool-Liquiditaet: ~{self.cost_model.pool_liquidity_eur:,.0f} EUR (Default)")
            print(f"   Swap-Fee:          {self.cost_model.swap_fee_rate*100:.2f}% pro Seite")
            print(f"   Market Drift:      {self.cost_model.market_drift_rate*100:.2f}%")
            print(f"   Failure Rate:      {self.cost_model.tx_failure_rate*100:.0f}%")
            sample_cost = self.cost_model.calculate(CAPITAL_PER_WALLET_EUR * POSITION_SIZE_PERCENT)
            print(f"   Kosten/Seite:     ~{sample_cost.total_cost_rate*100:.2f}% ({sample_cost.total_cost_eur:.4f} EUR)")
            print(f"   Round-Trip:       ~{self.cost_model.round_trip_cost_rate(CAPITAL_PER_WALLET_EUR * POSITION_SIZE_PERCENT)*100:.2f}%")
            print()

        for w in wallet_addresses:
            self.accounts[w] = WalletAccount(wallet=w)

        self._recover_orphaned_positions()

        self.connection_monitor = ConnectionHealthMonitor(
            emergency_callback=self._emergency_close_all_positions,
            reconnect_callback=self._check_for_missed_sells,
            failure_threshold_seconds=self.config['failure_threshold'],
            check_interval=5.0
        )

        if self.use_parallel:
            self.source = SolanaParallelSource(
                wallets=wallet_addresses, callback=self._handle_trade,
                num_parallel_keys=self.num_parallel_keys,
                connection_monitor=self.connection_monitor,
            )
        elif self.use_websocket:
            self.source = SolanaWebSocketSource(
                ws_url=WS_ENDPOINTS[NETWORK_MAINNET],
                http_url=WS_HTTP_ENDPOINTS[NETWORK_MAINNET],
                wallets=wallet_addresses, callback=self._handle_trade,
                connection_monitor=self.connection_monitor,
                reconnect_delay=self.config.get('reconnect_delay', 5.0),
            )
        else:
            self.source = SolanaPollingSource(
                rpc_http_url=RPC_HTTP_ENDPOINTS[NETWORK_MAINNET],
                wallets=wallet_addresses, callback=self._handle_trade,
                poll_interval=5, fast_poll_interval=0.5,
                connection_monitor=self.connection_monitor,
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

    # ──────────────────────────────────────────────────────────────────
    # KONFIGURATION
    # ──────────────────────────────────────────────────────────────────

    def _get_config_from_user(self):
        self.config = {}
        print()
        print("="*70)
        print("  KONFIGURATION")
        print("="*70)
        print()
        print(" Modus waehlen:")
        print("   [1] Analysis Mode  - eigener SL/TP, Transaktionskosten berechnet")
        print("   [2] Observer Mode  - folgt Wallet 1:1, kein SL/TP")
        print()

        while True:
            inp = input(" Modus [1]: ").strip()
            if not inp or inp == "1":
                self.observer_mode = False
                self.session_id = datetime.now().strftime("analysis_%Y%m%d_%H%M%S")
                break
            elif inp == "2":
                self.observer_mode = True
                self.session_id = datetime.now().strftime("observer_%Y%m%d_%H%M%S")
                break
            else:
                print("    Bitte 1 oder 2 eingeben!")

        n_keys = len(HELIUS_API_KEYS)
        print()
        print(" Trade-Source waehlen:")
        print("   [1] Multi-Key     - Helius Key-Rotation  (sequenziell, empfohlen)")
        print("   [2] Polling       - Helius HTTP RPC      (einzelner Key)")
        print(f"   [3] Parallel-Key  - mehrere Keys gleichzeitig ({n_keys} verfuegbar)")
        print()

        while True:
            inp = input(" Source [1]: ").strip()
            if not inp or inp == "1":
                self.use_websocket = True
                self.use_parallel  = False
                break
            elif inp == "2":
                self.use_websocket = False
                self.use_parallel  = False
                break
            elif inp == "3":
                self.use_parallel  = True
                self.use_websocket = False
                print()
                while True:
                    inp2 = input(f"   Anzahl parallele Keys [2] (max {n_keys}): ").strip()
                    if not inp2:
                        self.num_parallel_keys = min(2, n_keys)
                        break
                    try:
                        v = int(inp2)
                        if 1 <= v <= n_keys:
                            self.num_parallel_keys = v
                            break
                        print(f"    Bitte 1-{n_keys} eingeben!")
                    except ValueError:
                        print("    Bitte eine ganze Zahl eingeben!")
                break
            else:
                print("    Bitte 1, 2 oder 3 eingeben!")

        print()
        print("Druecke ENTER fuer Standardwerte")
        print()

        default_pos = 1 if not self.observer_mode else 5
        while True:
            inp = input(f" Max. gleichzeitige Positionen [{default_pos}]: ").strip()
            if not inp:
                self.max_positions = default_pos
                break
            try:
                v = int(inp)
                if v >= 1:
                    self.max_positions = v
                    break
                print("    Muss mindestens 1 sein!")
            except ValueError:
                print("    Bitte eine ganze Zahl eingeben!")

        if self.observer_mode:
            while True:
                inp = input(f" Max-Haltedauer pro Position (Min) [{self.OBSERVER_MAX_HOLD_MINUTES_DEFAULT}]: ").strip()
                if not inp:
                    self.observer_max_hold_minutes = self.OBSERVER_MAX_HOLD_MINUTES_DEFAULT
                    break
                try:
                    v = int(inp)
                    if v >= 1:
                        self.observer_max_hold_minutes = v
                        break
                    print("    Muss mindestens 1 Minute sein!")
                except ValueError:
                    print("    Bitte eine ganze Zahl eingeben!")

        while True:
            inp = input("  Connection Timeout (Sekunden) [30]: ").strip()
            if not inp:
                self.config['failure_threshold'] = 30
                break
            try:
                v = int(inp)
                if v > 0:
                    self.config['failure_threshold'] = v
                    break
                print("    Muss groesser als 0 sein!")
            except ValueError:
                print("    Bitte eine ganze Zahl eingeben!")

        print()
        print("="*70)
        if self.observer_mode:
            print("  OBSERVER MODE")
            print(f"   Max. Positionen:    {self.max_positions}")
            print(f"   Stagnation:         {self.OBSERVER_STAGNATION_MINUTES} Min -> schliessen")
            print(f"   Max-Haltedauer:     {self.observer_max_hold_minutes} Min -> schliessen")
            print(f"   Anti-Softlock:      Totalverlust nach {self.OBSERVER_MAX_PRICE_FAILURES}x kein Preis")
        else:
            print("  ANALYSIS MODE")
            print(f"   Positionen:         bis zu {self.max_positions} gleichzeitig")
            print(f"   Kapital:            {CAPITAL_PER_WALLET_EUR:.0f} EUR  ({POSITION_SIZE_PERCENT*100:.0f}% = {CAPITAL_PER_WALLET_EUR*POSITION_SIZE_PERCENT:.0f} EUR/Trade)")
            print(f"   Stop-Loss:          {self.STOP_LOSS_PERCENT:.0f}%   (aus Observer-DB wenn vorhanden)")
            print(f"   Take-Profit:       +{self.TAKE_PROFIT_PERCENT:.0f}%  (aus Observer-DB wenn vorhanden)")
            print(f"   Transaktionskosten: aktiviert (cost_model.py)")
        print(f"   Connection Timeout: {self.config['failure_threshold']}s")
        src_str = f"Parallel-Key ({self.num_parallel_keys} Keys)" if self.use_parallel else "Multi-Key" if self.use_websocket else "Polling"
        print(f"   Trade-Source:       {src_str}")
        print("="*70)
        print()

    # ──────────────────────────────────────────────────────────────────
    # EMERGENCY EXIT
    # ──────────────────────────────────────────────────────────────────

    async def _emergency_close_all_positions(self):
        print()
        print("="*70)
        print(" EMERGENCY: CONNECTION LOST  CLOSING ALL POSITIONS!")
        print("="*70)
        if not self.open_positions:
            print("   No open positions to close.")
            return
        for key, (account, last_price) in list(self.open_positions.items()):
            token = key[0]
            await self._close_position(token=token, account=account, price_eur=last_price,
                                        reason="EMERGENCY_EXIT_CONNECTION_LOST",
                                        trigger_label="Connection lost")
        print(" Emergency exit completed")
        print("="*70)
        print()

    # ──────────────────────────────────────────────────────────────────
    # RECONNECT
    # ──────────────────────────────────────────────────────────────────

    async def _check_for_missed_sells(self):
        if not self.open_positions:
            return
        logger.info("[MissedSells] Checking for missed SELLs...")
        missed = 0
        for key, (account, _) in list(self.open_positions.items()):
            token, wallet = key[0], account.wallet
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":[wallet,{"limit":10}]}
                    async with session.post(self.source.rpc_http_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        data = await resp.json()
                        if "error" in data:
                            continue
                    for sig_info in data.get("result", [])[:5]:
                        sig = sig_info.get("signature")
                        tx_payload = {"jsonrpc":"2.0","id":1,"method":"getTransaction","params":[sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]}
                        async with session.post(self.source.rpc_http_url, json=tx_payload, timeout=aiohttp.ClientTimeout(total=5)) as tx_resp:
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
                                await self._close_position(token=token, account=account,
                                                            price_eur=price or 0.0,
                                                            reason="MISSED_SELL_DETECTED_ON_RECONNECT",
                                                            trigger_label=f"{wallet[:8]}... sold (missed)",
                                                            price_missing=price is None)
                                break
            except Exception as e:
                logger.error(f"[MissedSells] Error {wallet[:8]}: {e}")
        logger.info(f"[MissedSells] {'Found '+str(missed)+' missed SELL(s)' if missed else 'No missed SELLs'}")

    # ──────────────────────────────────────────────────────────────────
    # TRADE HANDLER
    # ──────────────────────────────────────────────────────────────────

    async def _handle_trade(self, trade: TradeEvent):
        account = self.accounts.get(trade.wallet)
        if account is None:
            return
        pos_key = (trade.token, trade.wallet)
        in_fast = self.source and getattr(self.source, 'is_fast_polling', False)
        if not in_fast or pos_key in self.open_positions:
            logger.info(f" [{'obs' if self.observer_mode else 'anl'}] {trade.wallet[:8]}... {trade.side:4} {trade.amount:>12.2f} {trade.token[:8]}...")
        if trade.side == "BUY":
            await self._handle_buy(account, trade.token)
        elif trade.side == "SELL":
            await self._handle_sell(account, trade.token)

    async def _handle_buy(self, account: WalletAccount, token: str):
        if len(self.open_positions) >= self.max_positions:
            return
        key = (token, account.wallet)
        if key in self.open_positions:
            return

        price_eur = await self.oracle.get_price_eur(token)
        if not price_eur:
            logger.warning(f"[{'obs' if self.observer_mode else 'anl'}]   BUY skipped – no price for {token[:8]}...")
            return

        pos = account.open_position(token, price_eur,
                                     observer_mode=self.observer_mode,
                                     cost_model=self.cost_model)
        if not pos:
            return

        import time
        self.open_positions[key]    = (account, price_eur)
        self.price_fail_counts[key] = 0
        self._entry_costs[key]      = pos.entry_cost_eur
        self.total_buys += 1
        self.oracle.set_rate_limit_from_positions(len(self.open_positions))
        self.price_extremes[key] = (0.0, 0.0)

        if self.observer_mode:
            self.observer_last_price_time[key]   = time.monotonic()
            self.observer_entry_time[key]         = time.monotonic()
            self.observer_stagnation_tracker[key] = (price_eur, time.monotonic())
        else:
            self.inactivity_tracker[key] = (price_eur, time.monotonic())

        self.active_token   = token
        self.active_account = account
        self.last_price     = price_eur

        self.tracker.record_buy(session_id=self.session_id, wallet=account.wallet,
                                 token=token, amount=pos.amount, price_eur=price_eur,
                                 cost_eur=pos.entry_cost_eur)

        mode_tag = "OBSERVER" if self.observer_mode else "ANALYSIS"
        sl, tp   = self.tracker.get_sl_tp_for_wallet(account.wallet) if not self.observer_mode else (None, None)
        print()
        print("="*70)
        print(f" BUY [{mode_tag}]")
        print("="*70)
        print(f"Token:        {token[:20]}...")
        print(f"Wallet:       {account.wallet[:20]}...")
        print(f"Entry Price:  {price_eur:.8f} EUR")
        if not self.observer_mode and pos.entry_cost_eur > 0:
            print(f"Eff. Entry:   {pos.entry_price_eff:.8f} EUR  (inkl. {pos.entry_cost_eur:.4f} EUR Kosten)")
            if sl and tp:
                print(f"SL/TP:        {sl:.1f}% / +{tp:.1f}%  (aus Observer-DB)")
        print(f"Invested:     {pos.cost_eur:.2f} EUR")
        print(f"Amount:       {pos.amount:.4f}")
        print(f"Positionen:   {len(self.open_positions)}/{self.max_positions}")
        print("="*70)
        print()

        if self.price_update_task is None or self.price_update_task.done():
            self.price_update_task = asyncio.create_task(self._price_update_loop())

    async def _handle_sell(self, account: WalletAccount, token: str):
        key = (token, account.wallet)
        if key not in self.open_positions:
            return
        price_eur     = await self.oracle.get_price_eur(token, skip_cache=True)
        price_missing = price_eur is None
        if price_missing:
            price_eur = 0.0
        await self._close_position(token=token, account=account, price_eur=price_eur,
                                    reason="WALLET_SOLD",
                                    trigger_label=f"{account.wallet[:8]}... sold",
                                    price_missing=price_missing)

    # ──────────────────────────────────────────────────────────────────
    # POSITION SCHLIESSEN
    # ──────────────────────────────────────────────────────────────────

    async def _close_position(self, token: str, account: WalletAccount,
                               price_eur: float, reason: str, trigger_label: str,
                               price_missing: bool = False):
        record = account.close_position(token, price_eur,
                                         price_missing=price_missing,
                                         cost_model=self.cost_model if not self.observer_mode else None)
        if not record:
            return

        key = (token, account.wallet)
        self.open_positions.pop(key, None)
        self.price_fail_counts.pop(key, None)
        self.inactivity_tracker.pop(key, None)
        self.observer_last_price_time.pop(key, None)
        self.observer_entry_time.pop(key, None)
        self.observer_stagnation_tracker.pop(key, None)
        max_pct, min_pct = self.price_extremes.pop(key, (None, None))
        entry_cost = self._entry_costs.pop(key, 0.0)
        self.total_sells += 1
        self.oracle.set_rate_limit_from_positions(len(self.open_positions))

        if not self.observer_mode and reason != "INACTIVITY":
            if self.tracker.get_inactivity_tags(account.wallet) > 0:
                self.tracker.remove_inactivity_tag(account.wallet)

        pnl_eur      = record['pnl_eur']
        pnl_pct      = record['pnl_percent']
        eff_pnl      = record.get('effective_pnl_eur', pnl_eur)
        total_cost   = record.get('total_cost_eur', 0.0)
        result_emoji = "▲" if pnl_eur >= 0 else "▼"
        missing_tag  = "  [PREIS NICHT VERFUEGBAR – TOTALVERLUST]" if price_missing else ""

        print()
        print("="*70)
        print(f"{result_emoji} SELL [{reason}]{missing_tag}")
        print("="*70)
        print(f"Token:        {token[:20]}...")
        print(f"Trigger:      {trigger_label}")
        print(f"Wallet:       {account.wallet[:20]}...")
        print(f"Entry Price:  {record['entry_price_eur']:.8f} EUR")
        print(f"Exit Price:   {price_eur:.8f} EUR")
        print(f"Raw P&L:      {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%)")
        if not self.observer_mode and total_cost > 0:
            print(f"TX-Kosten:   -{total_cost:.4f} EUR  (BUY+SELL)")
            print(f"Eff. P&L:    {eff_pnl:+.2f} EUR ({record.get('effective_pnl_pct', 0):+.2f}%)")
        print(f"Slots:        {len(self.open_positions)}/{self.max_positions}")
        print("="*70)
        print()

        self.tracker.record_sell(
            session_id=self.session_id, wallet=account.wallet, token=token,
            amount=record['amount'], price_eur=price_eur,
            entry_price_eur=record['entry_price_eur'],
            price_missing=price_missing,
            max_price_pct=max_pct, min_price_pct=min_pct, reason=reason,
            cost_eur=record.get('sell_cost_eur', 0.0),
            entry_cost_eur=entry_cost,
        )

        if self.open_positions:
            nk, (na, np_) = next(iter(self.open_positions.items()))
            self.active_token, self.active_account, self.last_price = nk[0], na, np_
        else:
            self.active_token = self.active_account = None
            self.last_price   = 0.0
            if self.price_update_task and not self.price_update_task.done():
                self.price_update_task.cancel()

    # ──────────────────────────────────────────────────────────────────
    # PRICE MONITOR
    # ──────────────────────────────────────────────────────────────────

    async def _price_update_loop(self):
        if self.observer_mode:
            await self._price_update_loop_observer()
        else:
            await self._price_update_loop_analysis()

    async def _price_update_loop_observer(self):
        import time
        try:
            while True:
                interval = self.PRICE_UPDATE_INTERVAL_FAST if (self.source and getattr(self.source, 'is_fast_polling', False)) else self.PRICE_UPDATE_INTERVAL_NORMAL
                await asyncio.sleep(interval)
                if not self.open_positions:
                    break
                for key, (account, _) in list(self.open_positions.items()):
                    token = key[0]
                    pos   = account.positions.get(token)
                    if pos is None:
                        continue
                    current_price = await self.oracle.get_price_eur(token, skip_cache=True)
                    if current_price is None:
                        fails = self.price_fail_counts.get(key, 0) + 1
                        self.price_fail_counts[key] = fails
                        last_ok = self.observer_last_price_time.get(key, time.monotonic())
                        no_price_mins = (time.monotonic() - last_ok) / 60
                        if fails >= self.OBSERVER_MAX_PRICE_FAILURES:
                            await self._close_position(token=token, account=account, price_eur=0.0, reason="PRICE_UNAVAILABLE", trigger_label=f"{self.OBSERVER_MAX_PRICE_FAILURES}x kein Preis", price_missing=True)
                        elif no_price_mins >= self.OBSERVER_MAX_NO_PRICE_MINUTES:
                            await self._close_position(token=token, account=account, price_eur=0.0, reason="PRICE_UNAVAILABLE", trigger_label=f"{no_price_mins:.0f} Min kein Preis", price_missing=True)
                        continue
                    self.price_fail_counts[key] = 0
                    self.observer_last_price_time[key] = time.monotonic()
                    entry_price = pos.entry_price_eur
                    pnl_eur  = (current_price - entry_price) * pos.amount
                    pnl_pct  = ((current_price - entry_price) / entry_price) * 100
                    change_pct = ((current_price - self.open_positions[key][1]) / self.open_positions[key][1] * 100) if self.open_positions[key][1] > 0 else 0
                    self.open_positions[key] = (account, current_price)
                    if entry_price > 0:
                        cur_pct = pnl_pct
                        pm, pm2 = self.price_extremes.get(key, (cur_pct, cur_pct))
                        self.price_extremes[key] = (max(pm, cur_pct), min(pm2, cur_pct))
                    sp, st = self.observer_stagnation_tracker.get(key, (current_price, time.monotonic()))
                    if current_price != sp:
                        self.observer_stagnation_tracker[key] = (current_price, time.monotonic())
                        st = time.monotonic()
                    stag_mins = (time.monotonic() - st) / 60
                    hold_mins = (time.monotonic() - self.observer_entry_time.get(key, time.monotonic())) / 60
                    emoji = "▲" if pnl_eur > 0 else "▼" if pnl_eur < 0 else "─"
                    hint = ""
                    if stag_mins > 5:  hint += f" | Stagnation: {stag_mins:.0f}/{self.OBSERVER_STAGNATION_MINUTES}m"
                    if hold_mins > 10: hint += f" | Haltedauer: {hold_mins:.0f}/{self.observer_max_hold_minutes}m"
                    print(f"{emoji} [Observer] {token[:8]}... @ {current_price:.8f} EUR | P&L: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%) | {change_pct:+.2f}%{hint}")
                    if stag_mins >= self.OBSERVER_STAGNATION_MINUTES:
                        await self._close_position(token=token, account=account, price_eur=current_price, reason="OBSERVER_STAGNATION", trigger_label=f"Stagnation {stag_mins:.0f} Min")
                    elif hold_mins >= self.observer_max_hold_minutes:
                        await self._close_position(token=token, account=account, price_eur=current_price, reason="OBSERVER_MAX_HOLD", trigger_label=f"Max-Haltedauer {hold_mins:.0f} Min")
        except asyncio.CancelledError:
            logger.info("[Observer/PriceMonitor] Stopped")
        except Exception as e:
            logger.error(f"[Observer/PriceMonitor] Crashed: {e}")

    async def _price_update_loop_analysis(self):
        import time
        try:
            while True:
                interval = self.PRICE_UPDATE_INTERVAL_FAST if (self.source and getattr(self.source, 'is_fast_polling', False)) else self.PRICE_UPDATE_INTERVAL_NORMAL
                await asyncio.sleep(interval)
                if not self.open_positions:
                    break
                for key, (account, _) in list(self.open_positions.items()):
                    token = key[0]
                    pos   = account.positions.get(token)
                    if pos is None:
                        continue
                    current_price = await self.oracle.get_price_eur(token, skip_cache=True)
                    if current_price is None:
                        fails = self.price_fail_counts.get(key, 0) + 1
                        self.price_fail_counts[key] = fails
                        if fails >= MAX_PRICE_FAILURES:
                            await self._close_position(token=token, account=account, price_eur=0.0, reason="PRICE_UNAVAILABLE", trigger_label=f"{MAX_PRICE_FAILURES}x kein Preis", price_missing=True)
                        continue
                    self.price_fail_counts[key] = 0
                    entry_price = pos.entry_price_eur
                    pnl_eur  = (current_price - entry_price) * pos.amount
                    pnl_pct  = ((current_price - entry_price) / entry_price) * 100
                    change_pct = ((current_price - self.open_positions[key][1]) / self.open_positions[key][1] * 100) if self.open_positions[key][1] > 0 else 0
                    self.open_positions[key] = (account, current_price)
                    if entry_price > 0:
                        cur_pct = pnl_pct
                        pm, pm2 = self.price_extremes.get(key, (cur_pct, cur_pct))
                        self.price_extremes[key] = (max(pm, cur_pct), min(pm2, cur_pct))
                    lcp, lct = self.inactivity_tracker.get(key, (current_price, time.monotonic()))
                    if current_price != lcp:
                        self.inactivity_tracker[key] = (current_price, time.monotonic())
                        lct = time.monotonic()
                    timeout       = self.tracker.get_inactivity_timeout([account.wallet])
                    inactive_secs = time.monotonic() - lct
                    sl, tp = self.tracker.get_sl_tp_for_wallet(account.wallet)
                    emoji = "▲" if pnl_eur > 0 else "▼" if pnl_eur < 0 else "─"
                    # Effektiver PnL fuer Anzeige (approximiert)
                    approx_cost = (self._entry_costs.get(key, 0.0) +
                                   (self.cost_model.calculate(pos.cost_eur).total_cost_eur if self.cost_model else 0.0))
                    eff_pnl = pnl_eur - approx_cost
                    print(
                        f"{emoji} [Analysis] {token[:8]}... @ {current_price:.8f} EUR | "
                        f"Raw: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%) | "
                        f"Eff: {eff_pnl:+.2f} EUR | {change_pct:+.2f}%"
                        + (f" | Inaktiv: {inactive_secs/60:.1f}/{timeout//60}m" if inactive_secs > 30 else "")
                    )
                    if inactive_secs >= timeout:
                        tags = self.tracker.add_inactivity_tag(account.wallet)
                        await self._close_position(token=token, account=account, price_eur=current_price, reason="INACTIVITY", trigger_label=f"Inaktiv {inactive_secs/60:.1f} min")
                        continue
                    if pnl_pct <= sl:
                        await self._close_position(token=token, account=account, price_eur=current_price, reason="STOP_LOSS", trigger_label=f"Stop-Loss @ {pnl_pct:.1f}%")
                        continue
                    if pnl_pct >= tp:
                        await self._close_position(token=token, account=account, price_eur=current_price, reason="TAKE_PROFIT", trigger_label=f"Take-Profit @ +{pnl_pct:.1f}%")
        except asyncio.CancelledError:
            logger.info("[PriceMonitor] Stopped")
        except Exception as e:
            logger.error(f"[PriceMonitor] Crashed: {e}")

    # ──────────────────────────────────────────────────────────────────
    # RECOVERY & AUTO-EVALUATE
    # ──────────────────────────────────────────────────────────────────

    def _recover_orphaned_positions(self):
        orphans = self.tracker.get_orphaned_buys()
        if not orphans:
            return
        print()
        print("="*70)
        print(f" CRASH RECOVERY: {len(orphans)} verwaiste Position(en)")
        print("="*70)
        for o in orphans:
            ts = o['timestamp'][:16] if o['timestamp'] else '?'
            print(f"   {o['wallet'][:20]}...  {o['token'][:16]}...  {ts}")
        print()
        for o in orphans:
            self.tracker.close_orphaned_buy(
                buy_id=o['id'], wallet=o['wallet'], token=o['token'],
                amount=o['amount'], entry_price_eur=o['price_eur'],
                session_id=o['session_id'], cost_eur=o.get('cost_eur', 0.0),
            )
        print(f" {len(orphans)} Position(en) bereinigt.")
        print()

    def _auto_sync(self):
        try:
            import importlib.util
            deploy_path = str(Path(__file__).parent.parent.parent / "deploy.py")
            spec   = importlib.util.spec_from_file_location("deploy", deploy_path)
            deploy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(deploy)
            devices = deploy.load_devices()
            if not devices:
                return
            deploy.sync_all(push_after=True)
        except Exception as e:
            logger.debug(f"[Sync] Fehler: {e}")

    def _run_session_end_evaluate(self):
        import sqlite3
        if not self.observer_mode:
            return
        axiom_db = Path("data/axiom.db")
        obs_db   = Path("data/observer_performance.db")
        if not axiom_db.exists() or not obs_db.exists():
            return
        conn_ax    = sqlite3.connect(str(axiom_db))
        candidates = conn_ax.execute("SELECT wallet FROM axiom_wallets WHERE category = 'CandidateWallet' AND active = 1").fetchall()
        conn_ax.close()
        if not candidates:
            return
        conn_obs = sqlite3.connect(str(obs_db))
        ready, not_ready = [], []
        for (wallet,) in candidates:
            count = conn_obs.execute("""SELECT COUNT(*) FROM wallet_trades WHERE wallet=? AND side='SELL'
                AND reason NOT IN ('SESSION_ENDED','CRASH_RECOVERY') AND price_missing=0""", (wallet,)).fetchone()[0]
            (ready if count >= 20 else not_ready).append((wallet, count))
        conn_obs.close()
        print()
        print("="*70)
        print(f" SESSION-ENDE: {len(ready)} Candidates bereit für evaluate_wallets")
        print("="*70)
        if not ready:
            return
        try:
            from runners import evaluate_wallets
            evaluate_wallets.run()
        except Exception as e:
            logger.error(f"[AutoEvaluate] {e}")
        try:
            import sys as _sys
            _old = _sys.argv
            _sys.argv = ["find_wallets.py", "--apply"]
            import find_wallets
            find_wallets.main()
            _sys.argv = _old
        except Exception as e:
            logger.error(f"[AutoEvaluate] find_wallets: {e}")

    # ──────────────────────────────────────────────────────────────────
    # SIGNAL & SHUTDOWN
    # ──────────────────────────────────────────────────────────────────

    def _signal_handler(self, signum, frame):
        if self.shutting_down:
            return
        print("\n\n Stopping...")
        self.shutting_down = True
        if self.source:
            self.source.stop()

    async def _shutdown(self):
        if getattr(self, '_shutdown_called', False):
            return
        self._shutdown_called = True
        if self.price_update_task and not self.price_update_task.done():
            self.price_update_task.cancel()
        if self.connection_monitor:
            self.connection_monitor.stop()
        if self.open_positions:
            print(f"\n Closing {len(self.open_positions)} open position(s)...")
            for key, (account, _) in list(self.open_positions.items()):
                token = key[0]
                price = await self.oracle.get_price_eur(token, skip_cache=True)
                price_missing = price is None
                if price_missing:
                    price = 0.0
                await self._close_position(token=token, account=account, price_eur=price,
                                            reason="SESSION_ENDED", trigger_label="Session ended",
                                            price_missing=price_missing)
        rt = ""
        if self.start_time:
            d = datetime.now() - self.start_time
            rt = f"{int(d.total_seconds()//3600)}h {int((d.total_seconds()%3600)//60)}m {int(d.total_seconds()%60)}s"

        active_accounts = [a for a in self.accounts.values() if a.num_trades > 0]
        print()
        print("="*70)
        print(f" {'OBSERVER' if self.observer_mode else 'ANALYSIS'} RESULTS  |  Runtime: {rt}")
        print(f"   Session: {self.session_id}")
        print("="*70)

        if not active_accounts:
            print("   No trades observed.")
        else:
            sorted_accounts = sorted(active_accounts, key=lambda a: a.total_pnl_eur, reverse=True)
            header = f"  {'':1}  {'Wallet':<47} {'Trades':>6} {'Win%':>6} {'Raw PnL':>12}"
            if not self.observer_mode:
                header += f"  {'Eff. PnL':>12} {'SL':>7} {'TP':>7}"
            header += f"  {'Conf':>6} {'Label'}"
            print(header)
            print("  " + "-"*110)

            total_raw = 0.0
            total_eff = 0.0
            for acc in sorted_accounts:
                conf  = self.tracker.get_confidence(acc.wallet)
                label = self.tracker.get_strategy_label(acc.wallet)
                sl, tp = self.tracker.get_sl_tp_for_wallet(acc.wallet) if not self.observer_mode else (None, None)
                raw_pnl = acc.total_pnl_eur
                eff_pnl = acc.total_effective_pnl_eur
                total_raw += raw_pnl
                total_eff += eff_pnl
                marker = "+" if raw_pnl > 0 else "-" if raw_pnl < 0 else " "
                row = (f"  {marker}  {acc.wallet[:44]:<47}... "
                       f"{acc.num_trades:>5}x {acc.win_rate*100:>5.0f}% "
                       f"{raw_pnl:>+11.2f} EUR")
                if not self.observer_mode:
                    sl_str = f"{sl:.0f}%" if sl else "  -"
                    tp_str = f"+{tp:.0f}%" if tp else "  -"
                    row += f"  {eff_pnl:>+11.2f} EUR {sl_str:>7} {tp_str:>7}"
                row += f"  {conf:>6.2f} {label}"
                print(row)

            print("  " + "-"*110)
            total_row = f"     {'TOTAL':<47}{'':>6}{'':>6} {total_raw:>+11.2f} EUR"
            if not self.observer_mode:
                total_row += f"  {total_eff:>+11.2f} EUR"
            print(total_row)

        print()
        print(f"   BUYs: {self.total_buys}  SELLs: {self.total_sells}  Active: {len(active_accounts)}/{len(self.accounts)}")
        print("="*70)

        if self.observer_mode:
            self._run_session_end_evaluate()
        self._auto_sync()
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
