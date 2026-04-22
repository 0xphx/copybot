"""
Wallet Analysis Runner

Zwei Modi waehlbar beim Start:

[1] ANALYSIS MODE (bisheriges Verhalten)
    Jedes Wallet bekommt ein eigenes virtuelles Konto (1000 EUR, 20% pro Trade).
    Eigener Stop-Loss / Take-Profit / Inaktivitaets-Timeout.
    Misst: Wie wuerde sich unser Bot bei diesem Wallet verhalten?

[2] OBSERVER MODE (reines Wallet-Tracking)
    Folgt jedem Wallet 1:1: BUY wenn Wallet kauft, SELL wenn Wallet verkauft.
    KEIN eigener SL, KEIN eigener TP, KEIN Inaktivitaets-Close.
    Misst: Was macht das Wallet tatsaechlich?
    Trackt High/Low waehrend Position offen (fuer spaeteres dynamisches SL/TP).
    Session-ID Prefix: 'observer_'

    Timeout-Mechanismen (schliessen mit aktuellem Preis):
      - Preis-Stagnation: kein Preischange > 15 Min -> schliessen (OBSERVER_STAGNATION)
      - Max-Haltedauer:   Position > 60 Min offen  -> schliessen (OBSERVER_MAX_HOLD, anpassbar beim Start)

    Anti-Softlock (schliessen mit Totalverlust):
      - Kein Preis nach 10 Versuchen:  Totalverlust (0 EUR), price_missing=True
      - 30 Min gar kein Preis:         Totalverlust (0 EUR), price_missing=True
      - Emergency Exit bei Verbindungsverlust: letzter bekannter Preis
      - Reconnect: verpasste SELLs pruefen
      - Shutdown: aktueller Marktpreis, bei fehlendem Preis Totalverlust

Realitaetsnaehe hat immer Prioritaet.
"""

import asyncio
import aiohttp
import signal
import sys
import logging
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass, field

from config.network import (
    RPC_HTTP_ENDPOINTS, WS_ENDPOINTS, WS_HTTP_ENDPOINTS, NETWORK_MAINNET
)
from wallets.sync import sync_wallets
from observation.sources.solana_polling import SolanaPollingSource
from observation.sources.solana_ws_source import SolanaWebSocketSource
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

    def open_position(self, token: str, price_eur: float, observer_mode: bool = False) -> Optional[WalletPosition]:
        if token in self.positions or price_eur <= 0:
            return None
        if observer_mode:
            # Observer: Kapital ist virtuell und unbegrenzt (immer fixed 200 EUR pro Trade)
            invest = CAPITAL_PER_WALLET_EUR * POSITION_SIZE_PERCENT
        else:
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

    PRICE_UPDATE_INTERVAL_NORMAL = 10
    PRICE_UPDATE_INTERVAL_FAST   = 1
    STOP_LOSS_PERCENT     = -50.0
    TAKE_PROFIT_PERCENT   = 100.0

    # Observer: nach dieser Anzahl aufeinanderfolgender Preis-Fehler -> Totalverlust
    OBSERVER_MAX_PRICE_FAILURES = 10
    # Observer: nach dieser Zeit ohne JEGLICHEN Preis -> Totalverlust (Anti-Softlock)
    OBSERVER_MAX_NO_PRICE_MINUTES = 30
    # Observer: Position nach dieser Zeit schliessen (aktueller Preis), egal was
    # Anpassbar beim Start via Konfiguration
    OBSERVER_MAX_HOLD_MINUTES_DEFAULT = 60
    # Observer: Position schliessen wenn Preis sich X Min nicht veraendert hat
    OBSERVER_STAGNATION_MINUTES = 15

    def __init__(self):
        self.shutting_down  = False
        self.observer_mode: bool = False  # False = Analysis, True = Observer
        self.use_websocket: bool = False  # False = Polling (Helius), True = WebSocket (Public)
        self.source: Optional[SolanaPollingSource] = None
        self.oracle:             Optional[PriceOracle]            = None
        self.tracker:            Optional[WalletTracker]          = None
        self.connection_monitor: Optional[ConnectionHealthMonitor] = None

        self.accounts: Dict[str, WalletAccount] = {}

        self.max_positions: int = 1
        # (token, wallet) -> (account, last_price)
        self.open_positions:    Dict[tuple, tuple] = {}
        self.price_fail_counts: Dict[tuple, int]   = {}

        # Inaktivitaets-Tracking: (token, wallet) -> (letzter_preis, monotonic_time)
        self.inactivity_tracker: Dict[tuple, tuple] = {}

        # High/Low Tracking: (token, wallet) -> (max_price_pct, min_price_pct)
        self.price_extremes: Dict[tuple, tuple] = {}

        # Observer Anti-Softlock: (token, wallet) -> monotonic_time des letzten Preisabrufs
        self.observer_last_price_time: Dict[tuple, float] = {}

        # Observer Timeouts: (token, wallet) -> monotonic_time des BUY
        self.observer_entry_time: Dict[tuple, float] = {}
        # Observer Stagnation: (token, wallet) -> (letzter_preis, monotonic_time)
        self.observer_stagnation_tracker: Dict[tuple, tuple] = {}

        # Observer Max-Hold: anpassbar beim Start, Default aus Klassen-Konstante
        self.observer_max_hold_minutes: int = self.OBSERVER_MAX_HOLD_MINUTES_DEFAULT

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
        active_wallets = sync_wallets()
        if not active_wallets:
            logger.error(" No active wallets found!")
            return

        wallet_addresses = [w.wallet for w in active_wallets]

        self.oracle = PriceOracle()

        # Zeige Wallet-Uebersicht mit Analysis-DB Scores (falls vorhanden)
        # (Nur zur Info vor Moduswahl - danach wird mit der richtigen DB neu geladen)
        _preview_tracker = WalletTracker(db_path="data/wallet_performance.db")
        conf_map = _preview_tracker.get_confidence_map(wallet_addresses)
        known = [(w, s) for w, s in conf_map.items() if s != 0.2]
        print()
        print("="*70)
        print(" WALLET ANALYSIS / OBSERVER")
        print("="*70)
        print(f" {len(wallet_addresses)} Wallets geladen")
        if known:
            print(f" Bekannte Wallet Scores aus Analysis-DB ({len(known)}/{len(wallet_addresses)}):")
            for w, s in sorted(known, key=lambda x: -x[1])[:10]:
                label = _preview_tracker.get_strategy_label(w)
                print(f"   {w[:20]}...  conf={s:.2f}  [{label}]")
        print()

        # Config (inkl. Moduswahl + Source-Wahl) -> setzt self.observer_mode, self.use_websocket
        self._get_config_from_user()

        # Tracker mit der modusspezifischen DB initialisieren
        db_path = "data/observer_performance.db" if self.observer_mode else "data/wallet_performance.db"
        # Im Analysis-Modus: Observer-DB als SL/TP-Fallback mitgeben
        obs_path = "data/observer_performance.db" if not self.observer_mode else None
        self.tracker = WalletTracker(
            db_path=db_path,
            observer_mode=self.observer_mode,
            observer_db_path=obs_path,
        )

        for w in wallet_addresses:
            self.accounts[w] = WalletAccount(wallet=w)

        logger.info(f"[Wallets] Loaded {len(wallet_addresses)} wallets")

        # Crash-Recovery: verwaiste BUYs aus abgebrochenen Sessions schliessen
        self._recover_orphaned_positions()

        self.connection_monitor = ConnectionHealthMonitor(
            emergency_callback=self._emergency_close_all_positions,
            reconnect_callback=self._check_for_missed_sells,
            failure_threshold_seconds=self.config['failure_threshold'],
            check_interval=5.0
        )

        if self.use_websocket:
            self.source = SolanaWebSocketSource(
                ws_url=WS_ENDPOINTS[NETWORK_MAINNET],
                http_url=WS_HTTP_ENDPOINTS[NETWORK_MAINNET],
                wallets=wallet_addresses,
                callback=self._handle_trade,
                connection_monitor=self.connection_monitor,
                reconnect_delay=self.config.get('reconnect_delay', 5.0),
            )
        else:
            self.source = SolanaPollingSource(
                rpc_http_url=RPC_HTTP_ENDPOINTS[NETWORK_MAINNET],
                wallets=wallet_addresses,
                callback=self._handle_trade,
                poll_interval=5,
                fast_poll_interval=0.5,
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

    def _get_config_from_user(self):
        self.config = {}
        print()
        print("="*70)
        print("  KONFIGURATION")
        print("="*70)
        print()
        print(" Modus waehlen:")
        print("   [1] Analysis Mode  - eigener SL/TP, misst Bot-Performance")
        print("   [2] Observer Mode  - folgt Wallet 1:1, misst echtes Wallet-Verhalten")
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

        print()
        print(" Trade-Source waehlen:")
        print("   [P] Polling    - Helius HTTP RPC     (bisheriges System, ~277k Credits/Tag)")
        print("   [W] Free RPC   - 10 Public Endpunkte (neues System, 0 Credits, rotierend)")
        print()

        while True:
            inp = input(" Source [P]: ").strip().upper()
            if not inp or inp == "P":
                self.use_websocket = False
                break
            elif inp == "W":
                self.use_websocket = True
                break
            else:
                print("    Bitte P oder W eingeben!")

        print()
        print("Druecke ENTER fuer Standardwerte")
        print()

        if not self.observer_mode:
            # Analysis: max. gleichzeitige Positionen
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
        else:
            # Observer: konfigurierbare Max-Positionen
            while True:
                inp = input(" Max. gleichzeitige Positionen [5]: ").strip()
                if not inp:
                    self.max_positions = 5
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

        if self.observer_mode:
            while True:
                inp = input(f" Max-Haltedauer pro Position (Minuten) [{self.OBSERVER_MAX_HOLD_MINUTES_DEFAULT}]: ").strip()
                if not inp:
                    self.observer_max_hold_minutes = self.OBSERVER_MAX_HOLD_MINUTES_DEFAULT
                    break
                try:
                    v = int(inp)
                    if v < 1:
                        print("    Muss mindestens 1 Minute sein!")
                        continue
                    self.observer_max_hold_minutes = v
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
                    print("    Muss groesser als 0 sein!")
                    continue
                self.config['failure_threshold'] = v
                break
            except ValueError:
                print("    Bitte eine ganze Zahl eingeben!")

        if self.use_websocket:
            while True:
                inp = input("  WS Reconnect-Delay (Sekunden) [5]: ").strip()
                if not inp:
                    self.config['reconnect_delay'] = 5.0
                    break
                try:
                    v = float(inp)
                    if v <= 0:
                        print("    Muss groesser als 0 sein!")
                        continue
                    self.config['reconnect_delay'] = v
                    break
                except ValueError:
                    print("    Bitte eine Zahl eingeben!")

        print()
        print("="*70)
        if self.observer_mode:
            print("  OBSERVER MODE")
            print("   Folgt Wallet 1:1 (BUY/SELL exakt nach Wallet)")
            print("   Kein eigener SL / TP / Inaktivitaets-Timeout")
            print(f"   Max. Positionen:     {self.max_positions}")
            print(f"   Stagnation-Timeout:  {self.OBSERVER_STAGNATION_MINUTES} Min kein Preischange -> schliessen (aktueller Preis)")
            print(f"   Max-Haltedauer:      {self.observer_max_hold_minutes} Min -> schliessen (aktueller Preis)")
            print(f"   Anti-Softlock:       Totalverlust nach {self.OBSERVER_MAX_PRICE_FAILURES}x kein Preis")
            print(f"   Anti-Softlock:       Totalverlust nach {self.OBSERVER_MAX_NO_PRICE_MINUTES} Min ohne Preis")
            print(f"   Session-ID Prefix: observer_")
        else:
            print("  ANALYSIS MODE")
            print(f"   Modus:     {'1 globale Position' if self.max_positions == 1 else f'bis zu {self.max_positions} gleichzeitige Positionen'}")
            print(f"   Kapital:   {CAPITAL_PER_WALLET_EUR:.0f} EUR (je {POSITION_SIZE_PERCENT*100:.0f}% = {CAPITAL_PER_WALLET_EUR * POSITION_SIZE_PERCENT:.0f} EUR pro Trade)")
            print(f"   Stop-Loss: {self.STOP_LOSS_PERCENT:.0f}%")
            print(f"   Take-Profit: +{self.TAKE_PROFIT_PERCENT:.0f}%")
            print(f"   Preis-Ausfall: Totalverlust nach {MAX_PRICE_FAILURES}x kein Preis")
        print(f"   Connection Timeout: {self.config['failure_threshold']}s")
        source_label = "Free RPC Rotation (10 Endpunkte, 0 Credits)" if self.use_websocket else "Polling   (Helius HTTP, Credit-basiert)"
        print(f"   Trade-Source:       {source_label}")
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

        for key, (account, last_price) in list(self.open_positions.items()):
            token = key[0]
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

        for key, (account, _) in list(self.open_positions.items()):
            token  = key[0]
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
        pos_key = (trade.token, trade.wallet)
        if not in_fast_mode or pos_key in self.open_positions:
            logger.info(
                f" [analysis] {trade.wallet[:8]}... "
                f"{trade.side:4} {trade.amount:>12.2f} {trade.token[:8]}..."
            )

        if trade.side == "BUY":
            await self._handle_buy(account, trade.token)
        elif trade.side == "SELL":
            await self._handle_sell(account, trade.token)

    async def _handle_buy(self, account: WalletAccount, token: str):
        # Globales Positions-Limit (gilt fuer Analysis- und Observer-Modus)
        if len(self.open_positions) >= self.max_positions:
            return
        # Dieses Wallet hat diesen Token bereits offen -> ignorieren
        key = (token, account.wallet)
        if key in self.open_positions:
            return

        price_eur = await self.oracle.get_price_eur(token)
        if not price_eur:
            mode_tag = "[observer]" if self.observer_mode else "[analysis]"
            logger.warning(f"{mode_tag}   BUY skipped  no price for {token[:8]}...")
            return

        pos = account.open_position(token, price_eur, observer_mode=self.observer_mode)
        if not pos:
            return

        import time
        key = (token, account.wallet)
        self.open_positions[key]    = (account, price_eur)
        self.price_fail_counts[key] = 0
        self.total_buys += 1
        self.oracle.set_rate_limit_from_positions(len(self.open_positions))

        # High/Low Tracking initialisieren
        self.price_extremes[key] = (0.0, 0.0)

        if self.observer_mode:
            # Observer: alle Timer starten
            self.observer_last_price_time[key]    = time.monotonic()
            self.observer_entry_time[key]          = time.monotonic()
            self.observer_stagnation_tracker[key]  = (price_eur, time.monotonic())
        else:
            # Analysis: Inaktivitaets-Timer starten
            self.inactivity_tracker[key] = (price_eur, time.monotonic())

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

        mode_tag = "OBSERVER" if self.observer_mode else "ANALYSIS"
        slots_str = f"{len(self.open_positions)}/{self.max_positions}"
        print()
        print("="*70)
        print(f" BUY [{mode_tag}]")
        print("="*70)
        print(f"Token:        {token[:20]}...")
        print(f"Wallet:       {account.wallet[:20]}...")
        print(f"Entry Price:  {price_eur:.8f} EUR")
        print(f"Invested:     {pos.cost_eur:.2f} EUR")
        print(f"Amount:       {pos.amount:.4f}")
        print(f"Positionen:   {slots_str}")
        print("="*70)
        print()

        logger.info(
            f"[Portfolio]  BOUGHT {pos.amount:.4f} {token[:8]}... "
            f"@ {price_eur:.8f} EUR = {pos.cost_eur:.2f} EUR"
        )

        if self.price_update_task is None or self.price_update_task.done():
            self.price_update_task = asyncio.create_task(self._price_update_loop())

    async def _handle_sell(self, account: WalletAccount, token: str):
        key = (token, account.wallet)
        entry = self.open_positions.get(key)
        if entry is None:
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

        key = (token, account.wallet)
        self.open_positions.pop(key, None)
        self.price_fail_counts.pop(key, None)
        self.inactivity_tracker.pop(key, None)
        self.observer_last_price_time.pop(key, None)
        self.observer_entry_time.pop(key, None)
        self.observer_stagnation_tracker.pop(key, None)
        max_pct, min_pct = self.price_extremes.pop(key, (None, None))
        self.total_sells += 1
        self.oracle.set_rate_limit_from_positions(len(self.open_positions))

        # Tag-Abbau: nur im Analysis-Modus und nur wenn nicht Inaktivitaets-Close
        if not self.observer_mode and reason != "INACTIVITY":
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
            price_missing=price_missing,
            max_price_pct=max_pct,
            min_price_pct=min_pct,
            reason=reason,
        )

        if self.open_positions:
            next_key, (next_account, next_price) = next(iter(self.open_positions.items()))
            self.active_token   = next_key[0]
            self.active_account = next_account
            self.last_price     = next_price
        else:
            self.active_token   = None
            self.active_account = None
            self.last_price     = 0.0
            if self.price_update_task and not self.price_update_task.done():
                self.price_update_task.cancel()

    # 
    # AUTO-EVALUATE: Session-Ende
    # 

    CANDIDATE_MIN_TRADES = 20  # Mindest-Trades fuer Vergleich

    def _run_session_end_evaluate(self):
        """
        Wird am Session-Ende aufgerufen (nur Observer-Modus).
        Prueft alle CandidateWallets auf >= CANDIDATE_MIN_TRADES saubere Trades.
        Fuehrt evaluate_wallets aus wenn mindestens ein Candidate reif ist.
        Danach: find_wallets --apply um Candidate-Slots wieder aufzufuellen.
        """
        import sqlite3
        from pathlib import Path

        if not self.observer_mode:
            return

        axiom_db = Path("data/axiom.db")
        obs_db   = Path("data/observer_performance.db")
        if not axiom_db.exists() or not obs_db.exists():
            return

        # Alle aktiven CandidateWallets laden
        conn_ax = sqlite3.connect(str(axiom_db))
        candidates = conn_ax.execute(
            "SELECT wallet FROM axiom_wallets WHERE category = 'CandidateWallet' AND active = 1"
        ).fetchall()
        conn_ax.close()

        if not candidates:
            return

        # Trade-Zaehlung pro Candidate
        conn_obs = sqlite3.connect(str(obs_db))
        ready = []
        not_ready = []
        for (wallet,) in candidates:
            count = conn_obs.execute("""
                SELECT COUNT(*) FROM wallet_trades
                WHERE wallet = ? AND side = 'SELL'
                  AND reason NOT IN ('SESSION_ENDED', 'CRASH_RECOVERY')
                  AND price_missing = 0
            """, (wallet,)).fetchone()[0]
            if count >= self.CANDIDATE_MIN_TRADES:
                ready.append((wallet, count))
            else:
                not_ready.append((wallet, count))
        conn_obs.close()

        print()
        print("=" * 70)
        print(" SESSION-ENDE: CANDIDATE AUSWERTUNG")
        print("=" * 70)
        print(f"  Candidates gesamt:   {len(candidates)}")
        print(f"  Bereit (>={self.CANDIDATE_MIN_TRADES} Trades): {len(ready)}")
        print(f"  Noch nicht bereit:   {len(not_ready)}")
        for w, c in not_ready:
            print(f"    {w[:20]}...  {c}/{self.CANDIDATE_MIN_TRADES} Trades")
        print()

        if not ready:
            print("  Kein Candidate hat genug Trades. Kein Evaluate noetig.")
            print("=" * 70)
            print()
            return

        print(f"  {len(ready)} Candidate(s) bereit -> starte evaluate_wallets...")
        print("=" * 70)
        print()

        try:
            from runners import evaluate_wallets
            evaluate_wallets.run()
        except Exception as e:
            logger.error(f"[AutoEvaluate] Fehler: {e}")
            return

        # Nach Evaluate: Candidate-Slots mit find_wallets auffuellen
        print()
        print("=" * 70)
        print(" CANDIDATE-SLOTS AUFFUELLEN (find_wallets --apply)")
        print("=" * 70)
        print()
        try:
            import sys as _sys
            _old_argv = _sys.argv
            _sys.argv = ["find_wallets.py", "--apply"]
            import find_wallets
            find_wallets.main()
            _sys.argv = _old_argv
        except Exception as e:
            logger.error(f"[AutoEvaluate] find_wallets Fehler: {e}")
            print(f"  Tipp: Manuell ausfuehren: python find_wallets.py --apply")

    # 
    # PRICE MONITOR LOOP
    # 

    async def _price_update_loop(self):
        if self.observer_mode:
            await self._price_update_loop_observer()
        else:
            await self._price_update_loop_analysis()

    # --------------------------------------------------------------------
    # OBSERVER PRICE MONITOR
    # Trackt Preis + High/Low, kein SL/TP/Inactivity.
    # Anti-Softlock: Totalverlust nach N Failures ODER nach X Min ohne Preis.
    # --------------------------------------------------------------------
    async def _price_update_loop_observer(self):
        import time
        logger.info(
            f"[Observer/PriceMonitor] Started "
            f"(normal: {self.PRICE_UPDATE_INTERVAL_NORMAL}s | fast: {self.PRICE_UPDATE_INTERVAL_FAST}s | "
            f"Anti-Softlock: {self.OBSERVER_MAX_PRICE_FAILURES}x kein Preis "
            f"oder {self.OBSERVER_MAX_NO_PRICE_MINUTES} Min ohne Preis)"
        )
        try:
            while True:
                interval = (
                    self.PRICE_UPDATE_INTERVAL_FAST
                    if self.source and getattr(self.source, 'is_fast_polling', False)
                    else self.PRICE_UPDATE_INTERVAL_NORMAL
                )
                await asyncio.sleep(interval)

                if not self.open_positions:
                    break

                for key, (account, _) in list(self.open_positions.items()):
                    token = key[0]
                    pos = account.positions.get(token)
                    if pos is None:
                        continue

                    current_price = await self.oracle.get_price_eur(token, skip_cache=True)

                    if current_price is None:
                        fails = self.price_fail_counts.get(key, 0) + 1
                        self.price_fail_counts[key] = fails

                        # Anti-Softlock 1: zu viele aufeinanderfolgende Failures
                        if fails >= self.OBSERVER_MAX_PRICE_FAILURES:
                            logger.warning(
                                f"[Observer/PriceMonitor]  {token[:8]}... "
                                f"{self.OBSERVER_MAX_PRICE_FAILURES}x kein Preis -> Totalverlust"
                            )
                            await self._close_position(
                                token=token, account=account,
                                price_eur=0.0,
                                reason="PRICE_UNAVAILABLE",
                                trigger_label=f"{self.OBSERVER_MAX_PRICE_FAILURES}x kein Preis abrufbar",
                                price_missing=True
                            )
                            continue

                        # Anti-Softlock 2: zu lange kein Preis ueberhaupt
                        last_ok = self.observer_last_price_time.get(key, time.monotonic())
                        no_price_mins = (time.monotonic() - last_ok) / 60
                        if no_price_mins >= self.OBSERVER_MAX_NO_PRICE_MINUTES:
                            logger.warning(
                                f"[Observer/PriceMonitor]  {token[:8]}... "
                                f"{no_price_mins:.1f} Min kein Preis -> Totalverlust"
                            )
                            await self._close_position(
                                token=token, account=account,
                                price_eur=0.0,
                                reason="PRICE_UNAVAILABLE",
                                trigger_label=f"{no_price_mins:.0f} Min kein Preis abrufbar",
                                price_missing=True
                            )
                            continue

                        logger.warning(
                            f"[Observer/PriceMonitor]   No price for {token[:8]}... "
                            f"({fails}/{self.OBSERVER_MAX_PRICE_FAILURES} failures, "
                            f"{no_price_mins:.1f}/{self.OBSERVER_MAX_NO_PRICE_MINUTES} Min)"
                        )
                        continue

                    # Preis erfolgreich -> Failure-Counter und Timer zuruecksetzen
                    self.price_fail_counts[key] = 0
                    self.observer_last_price_time[key] = time.monotonic()

                    entry_price = pos.entry_price_eur
                    pnl_eur     = (current_price - entry_price) * pos.amount
                    pnl_pct     = ((current_price - entry_price) / entry_price) * 100
                    last_price  = self.open_positions[key][1]
                    change_pct  = ((current_price - last_price) / last_price * 100) if last_price > 0 else 0

                    self.open_positions[key] = (account, current_price)

                    # High/Low Tracking
                    if entry_price > 0:
                        current_pct = ((current_price - entry_price) / entry_price) * 100
                        prev_max, prev_min = self.price_extremes.get(key, (current_pct, current_pct))
                        self.price_extremes[key] = (
                            max(prev_max, current_pct),
                            min(prev_min, current_pct)
                        )

                    # Stagnation-Tracking: Preisaenderung registrieren
                    stag_price, stag_time = self.observer_stagnation_tracker.get(
                        key, (current_price, time.monotonic())
                    )
                    if current_price != stag_price:
                        self.observer_stagnation_tracker[key] = (current_price, time.monotonic())
                        stag_time = time.monotonic()
                    stagnation_mins = (time.monotonic() - stag_time) / 60

                    # Max-Haltedauer berechnen
                    entry_t   = self.observer_entry_time.get(key, time.monotonic())
                    hold_mins = (time.monotonic() - entry_t) / 60

                    # Status-Print mit Timeout-Hinweisen
                    emoji = "" if pnl_eur > 0 else "" if pnl_eur < 0 else ""
                    timeout_hint = ""
                    if stagnation_mins > 5:
                        timeout_hint += f" | Stagnation: {stagnation_mins:.0f}/{self.OBSERVER_STAGNATION_MINUTES} Min"
                    if hold_mins > 10:
                        timeout_hint += f" | Haltedauer: {hold_mins:.0f}/{self.observer_max_hold_minutes} Min"
                    print(
                        f"{emoji} [Observer] {token[:8]}... @ {current_price:.8f} EUR "
                        f"| P&L: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%) "
                        f"| Last {interval}s: {change_pct:+.2f}%"
                        + timeout_hint
                    )

                    # Stagnation-Timeout: Preis bewegt sich X Min nicht
                    if stagnation_mins >= self.OBSERVER_STAGNATION_MINUTES:
                        logger.warning(
                            f"[Observer/Stagnation]  {token[:8]}... "
                            f"kein Preischange seit {stagnation_mins:.0f} Min "
                            f"(limit {self.OBSERVER_STAGNATION_MINUTES} Min) -> schliessen"
                        )
                        await self._close_position(
                            token=token, account=account,
                            price_eur=current_price,
                            reason="OBSERVER_STAGNATION",
                            trigger_label=f"Kein Preischange seit {stagnation_mins:.0f} Min"
                        )
                        continue

                    # Max-Haltedauer-Timeout
                    if hold_mins >= self.observer_max_hold_minutes:
                        logger.warning(
                            f"[Observer/MaxHold]  {token[:8]}... "
                            f"seit {hold_mins:.0f} Min offen "
                            f"(limit {self.observer_max_hold_minutes} Min) -> schliessen"
                        )
                        await self._close_position(
                            token=token, account=account,
                            price_eur=current_price,
                            reason="OBSERVER_MAX_HOLD",
                            trigger_label=f"Max-Haltedauer {hold_mins:.0f} Min erreicht"
                        )
                        continue

        except asyncio.CancelledError:
            logger.info("[Observer/PriceMonitor] Stopped")
        except Exception as e:
            logger.error(f"[Observer/PriceMonitor] Crashed: {e}")

    # --------------------------------------------------------------------
    # ANALYSIS PRICE MONITOR (unveraendert)
    # --------------------------------------------------------------------
    async def _price_update_loop_analysis(self):
        import time
        logger.info(
            f"[PriceMonitor] Started "
            f"(normal: {self.PRICE_UPDATE_INTERVAL_NORMAL}s | fast: {self.PRICE_UPDATE_INTERVAL_FAST}s | "
            f"SL: {self.STOP_LOSS_PERCENT:.0f}% | TP: +{self.TAKE_PROFIT_PERCENT:.0f}% | "
            f"Max price failures: {MAX_PRICE_FAILURES})"
        )
        try:
            while True:
                interval = (
                    self.PRICE_UPDATE_INTERVAL_FAST
                    if self.source and getattr(self.source, 'is_fast_polling', False)
                    else self.PRICE_UPDATE_INTERVAL_NORMAL
                )
                await asyncio.sleep(interval)

                if not self.open_positions:
                    break

                for key, (account, _) in list(self.open_positions.items()):
                    token = key[0]
                    pos = account.positions.get(token)
                    if pos is None:
                        continue

                    current_price = await self.oracle.get_price_eur(token, skip_cache=True)

                    if current_price is None:
                        self.price_fail_counts[key] = self.price_fail_counts.get(key, 0) + 1
                        fails = self.price_fail_counts[key]
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

                    self.price_fail_counts[key] = 0

                    entry_price = pos.entry_price_eur
                    pnl_eur     = (current_price - entry_price) * pos.amount
                    pnl_pct     = ((current_price - entry_price) / entry_price) * 100
                    last_price  = self.open_positions[key][1]
                    change_pct  = ((current_price - last_price) / last_price * 100) if last_price > 0 else 0

                    self.open_positions[key] = (account, current_price)

                    # High/Low Tracking
                    if pos.entry_price_eur > 0:
                        current_pct = ((current_price - pos.entry_price_eur) / pos.entry_price_eur) * 100
                        prev_max, prev_min = self.price_extremes.get(key, (current_pct, current_pct))
                        self.price_extremes[key] = (
                            max(prev_max, current_pct),
                            min(prev_min, current_pct)
                        )

                    # Inaktivitaets-Tracking
                    last_changed_price, last_changed_time = self.inactivity_tracker.get(
                        key, (current_price, time.monotonic())
                    )
                    if current_price != last_changed_price:
                        self.inactivity_tracker[key] = (current_price, time.monotonic())
                        last_changed_time = time.monotonic()

                    timeout = self.tracker.get_inactivity_timeout([account.wallet])
                    inactive_secs = time.monotonic() - last_changed_time

                    emoji = "" if pnl_eur > 0 else "" if pnl_eur < 0 else ""
                    print(
                        f"{emoji} [PriceMonitor] {token[:8]}... @ {current_price:.8f} EUR "
                        f"| P&L: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%) "
                        f"| Last {interval}s: {change_pct:+.2f}%"
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

    def _recover_orphaned_positions(self):
        """
        Erkennt BUY-Trades ohne passendes SELL aus vergangenen Sessions
        (z.B. nach Reboot oder Stromausfall) und schliesst sie als CRASH_RECOVERY.
        Diese Trades werden gespeichert aber aus allen Stats-Berechnungen
        herausgefiltert (price_missing=True, reason=CRASH_RECOVERY).
        """
        orphans = self.tracker.get_orphaned_buys()
        if not orphans:
            return

        print()
        print("=" * 70)
        print(f" CRASH RECOVERY: {len(orphans)} verwaiste Position(en) gefunden")
        print(" (BUY ohne SELL aus einer abgebrochenen Session)")
        print("=" * 70)
        for o in orphans:
            ts = o['timestamp'][:16] if o['timestamp'] else '?'
            print(f"   {o['wallet'][:20]}...  {o['token'][:16]}...  "
                  f"Session: {o['session_id']}  Zeit: {ts}")
        print()
        print(" Diese Positionen werden als CRASH_RECOVERY geschlossen (price_missing).")
        print(" Sie fliessen NICHT in Statistiken ein.")
        print("=" * 70)
        print()

        for o in orphans:
            self.tracker.close_orphaned_buy(
                buy_id=o['id'],
                wallet=o['wallet'],
                token=o['token'],
                amount=o['amount'],
                entry_price_eur=o['price_eur'],
                session_id=o['session_id'],
            )

        print(f" {len(orphans)} verwaiste Position(en) bereinigt.")
        print()

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
            for key, (account, _) in list(self.open_positions.items()):
                token = key[0]
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

        mode_label = "OBSERVER RESULTS" if self.observer_mode else "WALLET ANALYSIS RESULTS"
        print()
        print("="*70)
        print(f" {mode_label}  |  Runtime: {runtime_str}")
        print(f"   Session: {self.session_id}")
        if self.observer_mode:
            print("   Modus: Observer (Wallet 1:1, kein SL/TP)")
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

        db_path = "data/observer_performance.db" if self.observer_mode else "data/wallet_performance.db"
        print(f" Performance saved to: {db_path}")
        print("="*70)

        # Auto-Evaluate am Session-Ende (nur Observer-Modus)
        if self.observer_mode:
            self._run_session_end_evaluate()

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
