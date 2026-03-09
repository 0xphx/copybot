"""
Paper Trading Runner
Vollständiger Testlauf mit virtuellem Kapital
"""
import asyncio
import signal
import sys
import logging
from datetime import datetime

from config.network import RPC_HTTP_ENDPOINTS, NETWORK_MAINNET
from wallets.sync import sync_wallets
from observation.sources.hybrid import HybridTradeSource
from observation.models import TradeEvent
from pattern.redundancy import RedundancyEngine, TradeSignal
from trading.portfolio import PaperPortfolio
from trading.price_oracle import PriceOracle, MockPriceOracle
from trading.realistic_oracle import RealisticMockOracle
from trading.engine import PaperTradingEngine
from trading.connection_monitor import ConnectionHealthMonitor
from trading.wallet_tracker import WalletTracker

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class PaperTradingRunner:
    """Runner für Paper Trading Tests"""
    
    def __init__(self):
        self.running = False
        self.shutting_down = False
        self.source = None
        self.portfolio = None
        self.oracle = None
        self.engine = None
        self.redundancy = None
        self.connection_monitor: ConnectionHealthMonitor = None
        self.tracker: WalletTracker = None

        # Statistiken
        self.total_signals = 0
        self.total_buys = 0
        self.total_sells = 0
    
    async def run(self):
        """Hauptloop"""
        
        print("="*70)
        print("📊 PAPER TRADING MODE - Virtual Trading Test")
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
        initial_capital = 1000.0  # 1000 EUR Startkapital
        self.portfolio = PaperPortfolio(initial_capital_eur=initial_capital)
        
        # 3. Price Oracle
        self.oracle = PriceOracle()

        # 4. WalletTracker + ConnectionHealthMonitor
        self.tracker = WalletTracker()
        self.connection_monitor = ConnectionHealthMonitor(
            emergency_callback=self._emergency_close_all_positions,
            reconnect_callback=None,  # paper_trading hat keinen Missed-SELL Check
            failure_threshold_seconds=30,
            check_interval=5.0
        )

        # 5. Redundancy Engine
        self.redundancy = RedundancyEngine(
            time_window_seconds=30,
            min_wallets=2,
            min_confidence=0.5
        )
        
        # Signal Handler für BUY Signals
        self.redundancy.on_signal = self._handle_signal
        
        print()
        print("🧠 [Trading Engine] Activated")
        print(f"   Initial Capital: {initial_capital:.2f} EUR")
        print(f"   Position Size: {self.portfolio.position_size_percent*100:.0f}%")
        print(f"   Strategy: Follow lead wallets")
        print()
        
        print("🧠 [Redundancy Engine] Activated")
        print(f"   Time Window: 30 seconds")
        print(f"   Min Wallets: 2")
        print(f"   Min Confidence: 50%")
        print()
        
        # 6. Hybrid Trade Source
        self.source = HybridTradeSource(
            rpc_http_url=RPC_HTTP_ENDPOINTS[NETWORK_MAINNET],
            real_wallets=wallet_addresses,
            callback=self._handle_trade,
            poll_interval=5,
            inject_fake_trades=True,
            fake_trade_interval=20,
            fast_poll_interval=0.5,
            connection_monitor=self.connection_monitor
        )

        # 7. Trading Engine
        self.engine = PaperTradingEngine(
            portfolio=self.portfolio,
            price_oracle=self.oracle,
            polling_source=self.source,
            wallet_tracker=self.tracker
        )

        await self.connection_monitor.start()
        
        # Signal Handler
        signal.signal(signal.SIGINT, self._signal_handler)
        
        self.running = True
        
        # Starte Source
        try:
            await self.source.connect()
        except asyncio.CancelledError:
            logger.info("\n[Runner] Shutting down...")
        finally:
            await self._shutdown()
    
    async def _handle_trade(self, trade: TradeEvent):
        """Handler für Trade Events"""
        # Log Trade
        source_emoji = "🔵" if "fake" in trade.source else "🟢"
        logger.info(
            f"{source_emoji} [{trade.source:15}] {trade.wallet[:8]}... "
            f"{trade.side:4} {trade.amount:>8.2f} {trade.token[:8]}..."
        )
        
        # 1. An Redundancy Engine weiterleiten
        signal = self.redundancy.process_trade(trade)
        
        # DEBUG: Zeige ob Signal erkannt wurde
        if signal:
            logger.debug(f"[DEBUG] Signal detected: {signal}")
        
        # 2. An Trading Engine weiterleiten (für SELL Detection)
        await self.engine.on_trade_event(trade)
        
        # 3. Stats
        if trade.side == "SELL":
            self.total_sells += 1
        elif trade.side == "BUY":
            # DEBUG Counter für BUYs
            pass
    
    async def _handle_signal(self, signal: TradeSignal):
        """Handler für Trade Signals von Redundancy Engine"""
        self.total_signals += 1
        
        # Nur BUY Signals
        if signal.side != "BUY":
            return
        
        print()
        print("="*70)
        print("🚨 STRONG BUY SIGNAL DETECTED!")
        print("="*70)
        print(f"Token:        {signal.token[:15]}...")
        print(f"Side:         {signal.side}")
        print(f"Wallets:      {signal.wallet_count} unique wallets")
        print(f"Total Amount: {signal.total_amount:.2f}")
        print(f"Avg Amount:   {signal.avg_amount:.2f}")
        print(f"Time Window:  {signal.time_window_seconds:.1f} seconds")
        print(f"Confidence:   {signal.confidence*100:.0f}%")
        print()
        print("Wallets involved:")
        for wallet in signal.wallets:
            print(f"  - {wallet[:15]}...")
        print("="*70)
        print()
        
        # An Trading Engine weiterleiten
        await self.engine.on_buy_signal(signal)
        self.total_buys += 1
    
    async def _emergency_close_all_positions(self):
        """🚨 Netzwerkausfall – alle Positionen sofort mit letztem bekannten Preis schließen"""
        print()
        print("="*70)
        print("🚨 EMERGENCY: CONNECTION LOST – CLOSING ALL POSITIONS!")
        print("="*70)

        if not self.portfolio or not self.portfolio.positions:
            print("   No open positions to close.")
            return

        for token in list(self.portfolio.positions.keys()):
            last_price = self.engine.last_prices.get(token, 0.0)
            print(f"   ❌ Force closed {token[:8]}... @ {last_price:.8f} EUR (last known price)")
            self.portfolio.close_position(
                token=token,
                price_eur=last_price,
                reason="(Emergency Exit – Connection lost)"
            )

        print("✅ Emergency exit completed")
        print("="*70)
        print()

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
        # Nicht prüfen ob shutting_down - muss immer laufen!
        # Aber setzen um mehrfache Calls zu verhindern
        if hasattr(self, '_shutdown_called') and self._shutdown_called:
            return
        self._shutdown_called = True

        if self.connection_monitor:
            self.connection_monitor.stop()

        print("\n")
        print("="*70)
        print("📊 PAPER TRADING SESSION ENDED")
        print("="*70)
        
        # Close all open positions
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
        
        # Stats
        print(f"\n📈 Trading Statistics:")
        print(f"   Total Signals:    {self.total_signals}")
        print(f"   Total Buys:       {self.total_buys}")
        print(f"   Total Sells:      {self.total_sells}")
        print()
        
        # Portfolio Summary
        if self.engine:
            await self.engine.print_summary()
        
        # Connection Health
        if self.connection_monitor:
            status = self.connection_monitor.get_status()
            print(f"🛡️  Connection Health:")
            print(f"   Final Status:         {'Connected' if status['connected'] else 'Disconnected'}")
            print(f"   Total Disconnections: {status['total_disconnections']}")
            if status['emergency_triggered']:
                print(f"   ⚠️  Emergency Exit was triggered!")
            print()

        # Price Statistics
        if hasattr(self.oracle, 'print_all_stats'):
            self.oracle.print_all_stats()
        
        # Save Portfolio
        if self.portfolio:
            filepath = f"data/paper_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            self.portfolio.save_to_file(filepath)
            print(f"\n💾 Portfolio saved to: {filepath}\n")
        
        # Cleanup
        if self.oracle:
            await self.oracle.close()


async def main():
    """Entry Point"""
    runner = PaperTradingRunner()
    await runner.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
