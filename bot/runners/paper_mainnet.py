"""
Paper Trading Runner - PURE MAINNET (Keine Fake Trades)
Nur echte Mainnet Trades für realistische Tests
🛡️ MIT CONNECTION HEALTH MONITORING + HYBRID APPROACH
"""
import asyncio
import signal
import sys
import logging
from datetime import datetime
import aiohttp

from config.network import RPC_HTTP_ENDPOINTS, NETWORK_MAINNET
from wallets.sync import sync_wallets
from observation.sources.solana_polling import SolanaPollingSource
from observation.models import TradeEvent
from pattern.redundancy import RedundancyEngine, TradeSignal
from trading.portfolio import PaperPortfolio
from trading.price_oracle import PriceOracle, MockPriceOracle
from trading.engine import PaperTradingEngine
from trading.connection_monitor import ConnectionHealthMonitor
from trading.wallet_tracker import WalletTracker

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class PaperTradingMainnetRunner:
    """Runner für Paper Trading - NUR MAINNET"""
    
    def __init__(self):
        self.running = False
        self.shutting_down = False
        self.source = None
        self.portfolio = None
        self.oracle = None
        self.engine = None
        self.redundancy = None
        self.connection_monitor = None
        
        # Konfigurierbare Parameter
        self.config = {}
        
        # Statistiken
        self.total_signals = 0
        self.total_buys = 0
        self.total_sells = 0
        
        # Laufzeit Tracking
        self.start_time = None
    
    def _get_config_from_user(self):
        """
        🎛️ INTERACTIVE SETUP
        Fragt Benutzer nach Konfiguration
        """
        print()
        print("="*70)
        print("⚙️  BOT CONFIGURATION")
        print("="*70)
        print()
        print("Drücke ENTER für Standardwerte")
        print()
        
        # 1. Initial Capital
        while True:
            capital_input = input("💰 Initial Capital (EUR) [1000]: ").strip()
            if not capital_input:
                self.config['initial_capital'] = 1000.0
                break
            try:
                capital = float(capital_input)
                if capital <= 0:
                    print("   ❌ Muss größer als 0 sein!")
                    continue
                self.config['initial_capital'] = capital
                break
            except ValueError:
                print("   ❌ Bitte eine Zahl eingeben!")
        
        # 2. Position Size
        while True:
            size_input = input("📊 Position Size (%) [20]: ").strip()
            if not size_input:
                self.config['position_size'] = 0.20
                break
            try:
                size = float(size_input)
                if size <= 0 or size > 100:
                    print("   ❌ Muss zwischen 0 und 100 sein!")
                    continue
                self.config['position_size'] = size / 100
                break
            except ValueError:
                print("   ❌ Bitte eine Zahl eingeben!")
        
        # 3. Redundancy: Time Window
        while True:
            window_input = input("⏱️  Time Window (Sekunden) [30]: ").strip()
            if not window_input:
                self.config['time_window'] = 30
                break
            try:
                window = int(window_input)
                if window <= 0:
                    print("   ❌ Muss größer als 0 sein!")
                    continue
                self.config['time_window'] = window
                break
            except ValueError:
                print("   ❌ Bitte eine ganze Zahl eingeben!")
        
        # 4. Redundancy: Min Wallets
        while True:
            wallets_input = input("👥 Min Wallets für Signal [2]: ").strip()
            if not wallets_input:
                self.config['min_wallets'] = 2
                break
            try:
                wallets = int(wallets_input)
                if wallets <= 0:
                    print("   ❌ Muss größer als 0 sein!")
                    continue
                self.config['min_wallets'] = wallets
                break
            except ValueError:
                print("   ❌ Bitte eine ganze Zahl eingeben!")
        
        # 5. Redundancy: Min Confidence
        while True:
            conf_input = input("🎯 Min Confidence (%) [50]: ").strip()
            if not conf_input:
                self.config['min_confidence'] = 0.5
                break
            try:
                conf = float(conf_input)
                if conf <= 0 or conf > 100:
                    print("   ❌ Muss zwischen 0 und 100 sein!")
                    continue
                self.config['min_confidence'] = conf / 100
                break
            except ValueError:
                print("   ❌ Bitte eine Zahl eingeben!")
        
        # 6. Connection Monitor: Failure Threshold
        while True:
            threshold_input = input("🛡️  Connection Timeout (Sekunden) [30]: ").strip()
            if not threshold_input:
                self.config['failure_threshold'] = 30
                break
            try:
                threshold = int(threshold_input)
                if threshold <= 0:
                    print("   ❌ Muss größer als 0 sein!")
                    continue
                self.config['failure_threshold'] = threshold
                break
            except ValueError:
                print("   ❌ Bitte eine ganze Zahl eingeben!")
        
        # 7. Price Update Interval
        while True:
            interval_input = input("📈 Price Update Interval (Sekunden) [10]: ").strip()
            if not interval_input:
                self.config['price_update_interval'] = 10
                break
            try:
                interval = int(interval_input)
                if interval <= 0:
                    print("   ❌ Muss größer als 0 sein!")
                    continue
                self.config['price_update_interval'] = interval
                break
            except ValueError:
                print("   ❌ Bitte eine ganze Zahl eingeben!")
        
        # 8. Stop-Loss
        while True:
            sl_input = input("🛑 Stop-Loss (%) [-50]: ").strip()
            if not sl_input:
                self.config['stop_loss'] = -50.0
                break
            try:
                sl = float(sl_input.lstrip('-'))
                if sl <= 0 or sl >= 100:
                    print("   ❌ Muss zwischen 0 und 100 sein (z.B. 15 für -15%)!")
                    continue
                self.config['stop_loss'] = -sl
                break
            except ValueError:
                print("   ❌ Bitte eine Zahl eingeben (z.B. 15)!")
        
        # 9. Take-Profit
        while True:
            tp_input = input("🎯 Take-Profit (%) [100]: ").strip()
            if not tp_input:
                self.config['take_profit'] = 100.0
                break
            try:
                tp = float(tp_input.lstrip('+'))
                if tp <= 0:
                    print("   ❌ Muss größer als 0 sein!")
                    continue
                self.config['take_profit'] = tp
                break
            except ValueError:
                print("   ❌ Bitte eine Zahl eingeben (z.B. 50)!")
        
        print()
        print("="*70)
        print("✅ Konfiguration abgeschlossen!")
        print("="*70)
    
    async def run(self):
        """Hauptloop"""
        
        # 🎛️ Setup: Hole Konfiguration vom Benutzer
        self._get_config_from_user()
        
        print()
        print("="*70)
        print("📊 PAPER TRADING MODE - PURE MAINNET (No Fake Trades)")
        print("🛡️  WITH CONNECTION HEALTH MONITORING + HYBRID APPROACH")
        print("="*70)
        print()
        
        # 1. Wallets laden
        active_wallets = sync_wallets()
        if not active_wallets:
            logger.error("❌ No active wallets found!")
            return
        
        wallet_addresses = [w.wallet for w in active_wallets]
        logger.info(f"[Wallets] Loaded {len(wallet_addresses)} wallets")
        print()
        
        # 2. Portfolio initialisieren
        self.portfolio = PaperPortfolio(
            initial_capital_eur=self.config['initial_capital']
        )
        self.portfolio.position_size_percent = self.config['position_size']
        
        # 3. Price Oracle
        self.oracle = PriceOracle()
        
        # 4. 🛡️ Connection Health Monitor
        self.connection_monitor = ConnectionHealthMonitor(
            emergency_callback=self._emergency_close_all_positions,
            reconnect_callback=self._check_for_missed_sells,
            failure_threshold_seconds=self.config['failure_threshold'],
            check_interval=5.0
        )
        
        # 5. Redundancy Engine (mit historischen Confidence Scores falls vorhanden)
        tracker = WalletTracker()
        self.tracker = tracker
        self.redundancy = RedundancyEngine(
            time_window_seconds=self.config['time_window'],
            min_wallets=self.config['min_wallets'],
            min_confidence=self.config['min_confidence'],
            wallet_tracker=tracker
        )
        
        # Signal Handler für BUY/SELL Signals von Redundancy Engine
        self.redundancy.on_signal = self._handle_signal
        
        print()
        print("🧠 [Trading Engine] Activated")
        print(f"   Initial Capital: {self.config['initial_capital']:.2f} EUR")
        print(f"   Position Size: {self.config['position_size']*100:.0f}%")
        print(f"   Strategy: Follow lead wallets")
        print()
        
        print("🧠 [Redundancy Engine] Activated")
        print(f"   Time Window: {self.config['time_window']} seconds")
        print(f"   Min Wallets: {self.config['min_wallets']}")
        print(f"   Min Confidence: {self.config['min_confidence']*100:.0f}%")
        print()
        
        print("🛡️  [Connection Monitor] Activated")
        print(f"   Failure Threshold: {self.config['failure_threshold']} seconds")
        print(f"   Check Interval: 5 seconds")
        print(f"   Emergency Action: Close all positions")
        print(f"   Reconnect Action: Check for missed SELLs")
        print()
        
        print("📈 [Price Monitor] Activated")
        print(f"   Update Interval: {self.config['price_update_interval']} seconds")
        print(f"   Stop-Loss:       {self.config['stop_loss']:.0f}%")
        print(f"   Take-Profit:     +{self.config['take_profit']:.0f}%")
        print()
        
        print("🌐 [Mode] PURE MAINNET - No fake trades")
        print("   Watching real Solana transactions only")
        print()
        
        # 6. Polling Source
        self.source = SolanaPollingSource(
            rpc_http_url=RPC_HTTP_ENDPOINTS[NETWORK_MAINNET],
            wallets=wallet_addresses,
            callback=self._handle_trade,
            poll_interval=5,
            fast_poll_interval=0.5,
            connection_monitor=self.connection_monitor
        )
        
        # 7. Trading Engine
        self.engine = PaperTradingEngine(
            portfolio=self.portfolio,
            price_oracle=self.oracle,
            polling_source=self.source,
            price_update_interval=self.config['price_update_interval'],
            stop_loss_percent=self.config['stop_loss'],
            take_profit_percent=self.config['take_profit'],
            wallet_tracker=tracker
        )
        
        # Signal Handler
        signal.signal(signal.SIGINT, self._signal_handler)
        
        self.running = True
        self.start_time = datetime.now()
        
        print("⏳ Waiting for real trades on Mainnet...")
        print("   (This might take a while if wallets are not active)")
        print()
        
        try:
            await self.source.connect()
        except asyncio.CancelledError:
            logger.info("\n[Runner] Shutting down...")
        finally:
            await self._shutdown()
    
    async def _emergency_close_all_positions(self):
        """🛡️ EMERGENCY EXIT - Verbindung verloren"""
        print()
        print("="*70)
        print("🚨 EMERGENCY: CONNECTION LOST - CLOSING ALL POSITIONS!")
        print("="*70)
        
        if not self.portfolio or not self.portfolio.positions:
            print("   No open positions to close")
            return
        
        positions_closed = 0
        for token in list(self.portfolio.positions.keys()):
            position = self.portfolio.positions[token]
            entry_price = position.entry_price_eur
            self.portfolio.close_position(
                token=token,
                price_eur=entry_price,
                reason="EMERGENCY_EXIT_CONNECTION_LOST"
            )
            print(f"   ❌ Force closed {token[:8]}... @ {entry_price:.4f} EUR (break-even)")
            positions_closed += 1
        
        print(f"\n✅ Emergency exit completed ({positions_closed} positions closed)")
        print("="*70)
        print()
    
    async def _check_for_missed_sells(self):
        """🔄 RECONNECT CALLBACK - Prüft verpasste SELLs"""
        if not self.portfolio or not self.portfolio.positions:
            logger.info("[MissedSells] No open positions to check")
            return
        
        logger.info("[MissedSells] Checking for missed SELLs during offline period...")
        missed_sells_found = 0
        
        for token in list(self.portfolio.positions.keys()):
            trigger_wallets = self.engine.position_trigger_wallets.get(token, set())
            
            if not trigger_wallets:
                logger.warning(f"[MissedSells] No trigger wallets found for {token[:8]}...")
                continue
            
            logger.info(f"[MissedSells] Checking {len(trigger_wallets)} wallets for {token[:8]}...")
            
            for wallet in trigger_wallets:
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
                        ) as response:
                            data = await response.json()
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
                                ) as tx_response:
                                    tx_data = await tx_response.json()
                                    if "error" in tx_data:
                                        continue
                                    
                                    tx = tx_data.get("result")
                                    if not tx:
                                        continue
                                    
                                    trade_event = self.source.extract_trade(tx, wallet, sig)
                                    if trade_event and trade_event.token == token and trade_event.side == "SELL":
                                        missed_sells_found += 1
                                        current_price = await self.oracle.get_price_eur(token)
                                        if current_price:
                                            self.portfolio.close_position(
                                                token=token,
                                                price_eur=current_price,
                                                reason="MISSED_SELL_DETECTED_ON_RECONNECT"
                                            )
                                            if token in self.engine.position_trigger_wallets:
                                                del self.engine.position_trigger_wallets[token]
                                            if not self.portfolio.positions:
                                                if hasattr(self.source, 'stop_watching_wallets'):
                                                    self.source.stop_watching_wallets()
                                        break
                
                except Exception as e:
                    logger.error(f"[MissedSells] Error checking wallet {wallet[:8]}: {e}")
                    continue
        
        if missed_sells_found > 0:
            logger.info(f"[MissedSells] ✅ Found and processed {missed_sells_found} missed SELL(s)")
        else:
            logger.info(f"[MissedSells] ✅ No missed SELLs detected")
    
    async def _handle_trade(self, trade: TradeEvent):
        """
        Handler für ALLE Trade Events.
        
        WICHTIG: Jeder Trade wird IMMER an die Redundancy Engine weitergeleitet.
        Der Fast-Mode-Filter betrifft nur den Log-Output, nie die Logik.
        """

        # ─── 1. IMMER: Redundancy Engine verarbeitet jeden Trade ──────────────
        self.redundancy.process_trade(trade)

        # ─── 2. IMMER: Trading Engine prüft auf SELL für offene Positionen ────
        await self.engine.on_trade_event(trade)

        # ─── 3. Stats ─────────────────────────────────────────────────────────
        if trade.side == "SELL":
            self.total_sells += 1

        # ─── 4. Log-Output (Fast Mode filtert Noise raus) ─────────────────────
        in_fast_mode = (
            self.source and
            hasattr(self.source, 'is_fast_polling') and
            self.source.is_fast_polling
        )

        if in_fast_mode:
            # Im Fast Mode: nur Trades für Token mit offener Position zeigen
            if trade.token in self.portfolio.positions:
                logger.info(
                    f"🟢 [mainnet_real  ] {trade.wallet[:8]}... "
                    f"{trade.side:4} {trade.amount:>8.2f} {trade.token[:8]}..."
                )
            # else: kein Log (kein return, da Logik oben bereits erledigt)
        else:
            # Normal Mode: alles loggen
            logger.info(
                f"🟢 [mainnet_real  ] {trade.wallet[:8]}... "
                f"{trade.side:4} {trade.amount:>8.2f} {trade.token[:8]}..."
            )
    
    async def _handle_signal(self, signal_obj: TradeSignal):
        """
        Handler für Signals von Redundancy Engine.
        Verarbeitet BUY und SELL Signals.
        """
        self.total_signals += 1
        
        if signal_obj.side == "BUY":
            # 🚫 SKIP: Irgendeine Position ist bereits offen
            if self.portfolio.positions:
                logger.debug(
                    f"[Runner] Ignoring BUY for {signal_obj.token[:8]}... "
                    f"(position already open – waiting for SELL first)"
                )
                return
            
            # Zeige BUY Signal Box
            # Strategie-Labels und SL/TP für beteiligte Wallets
            sl, tp = self.tracker.get_sl_tp_for_wallets(signal_obj.wallets)
            wallet_labels = [
                (w, self.tracker.get_strategy_label(w))
                for w in signal_obj.wallets
            ]

            print()
            print("="*70)
            print("🚨 STRONG BUY SIGNAL DETECTED!")
            print("="*70)
            print(f"Token:        {signal_obj.token[:15]}...")
            print(f"Wallets:      {signal_obj.wallet_count} unique wallets")
            print(f"Time Window:  {signal_obj.time_window_seconds:.1f} seconds")
            print(f"Confidence:   {signal_obj.confidence*100:.0f}%")
            print()
            print("Wallets involved:")
            for w, label in wallet_labels:
                print(f"  - {w[:20]}...  [{label}]")
            print()
            print(f"Strategy SL/TP: Stop-Loss {sl:.0f}%  |  Take-Profit +{tp:.0f}%")
            print("="*70)
            print()
            
            await self.engine.on_buy_signal(signal_obj)
            self.total_buys += 1

        elif signal_obj.side == "SELL":
            # SELL Signal von Redundancy Engine – nur loggen
            # Die eigentliche Position-Schließung läuft über on_trade_event
            # (direkt pro Wallet, nicht auf Redundancy-Ebene)
            logger.debug(
                f"[Runner] SELL signal from redundancy: {signal_obj.token[:8]}... "
                f"({signal_obj.wallet_count} wallets)"
            )
    
    def _signal_handler(self, signum, frame):
        """CTRL+C Handler"""
        if self.shutting_down:
            return
        print("\n\n🛑 Stopping...")
        self.shutting_down = True
        self.running = False
        if self.source:
            self.source.stop()
    
    async def _shutdown(self):
        """Shutdown Prozedur"""
        if hasattr(self, '_shutdown_called') and self._shutdown_called:
            return
        self._shutdown_called = True
        
        print("\n")
        print("="*70)
        print("📊 PAPER TRADING SESSION ENDED")
        print("="*70)
        
        if self.start_time:
            end_time = datetime.now()
            runtime = end_time - self.start_time
            hours = int(runtime.total_seconds() // 3600)
            minutes = int((runtime.total_seconds() % 3600) // 60)
            seconds = int(runtime.total_seconds() % 60)
            print(f"⏱️  Runtime: {hours}h {minutes}m {seconds}s")
            print()
        
        if self.portfolio and self.portfolio.positions:
            print("\n📊 Closing all open positions...\n")
            for token in list(self.portfolio.positions.keys()):
                price = await self.oracle.get_price_eur(token)
                if price:
                    self.portfolio.close_position(
                        token=token,
                        price_eur=price,
                        reason="(Session ended)"
                    )
            print()
        
        print(f"\n📈 Trading Statistics:")
        print(f"   Total Signals:    {self.total_signals}")
        print(f"   Total Buys:       {self.total_buys}")
        print(f"   Total Sells:      {self.total_sells}")
        print()
        
        if self.connection_monitor:
            status = self.connection_monitor.get_status()
            print(f"🛡️  Connection Health:")
            print(f"   Final Status: {'Connected' if status['connected'] else 'Disconnected'}")
            print(f"   Total Disconnections: {status['total_disconnections']}")
            if status['emergency_triggered']:
                print(f"   ⚠️  Emergency Exit was triggered!")
            print()
        
        if self.engine:
            await self.engine.print_summary()
        
        if hasattr(self.oracle, 'print_all_stats'):
            self.oracle.print_all_stats()
        
        if self.portfolio:
            filepath = f"data/paper_mainnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            self.portfolio.save_to_file(filepath)
            print(f"\n💾 Portfolio saved to: {filepath}\n")
        
        if self.oracle:
            await self.oracle.close()
        
        if self.engine:
            await self.engine.stop()


async def main():
    """Entry Point"""
    runner = PaperTradingMainnetRunner()
    await runner.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
