"""
Hybrid Runner - Mainnet + Fake Trades
Perfekt zum Testen der Redundancy Engine!
"""
import asyncio
import sys
from observation.sources.hybrid import HybridTradeSource
from config.network import get_http_url, print_network_info, NETWORK_MAINNET
from wallets.sync import sync_wallets
from pattern.redundancy import RedundancyEngine, TradeSignal


redundancy_engine = None


async def handle_trade(event):
    """Trade Handler mit Source Indicator"""
    # Farbige Ausgabe je nach Source
    if event.source == "mainnet_real":
        prefix = "🟢 [REAL]"
    elif event.source == "hybrid_fake":
        prefix = "🔵 [FAKE]"
    else:
        prefix = "[Trade]"
    
    print(
        f"{prefix} {event.wallet[:8]}... "
        f"{event.side.upper()} {event.amount:.4f} {event.token[:8]}... "
    )
    
    # Pattern Detection
    if redundancy_engine:
        signal = redundancy_engine.process_trade(event)


def handle_signal(signal: TradeSignal):
    """Handler für erkannte Signals"""
    print()
    print("=" * 70)
    print(f"🚨 STRONG {signal.side} SIGNAL DETECTED!")
    print("=" * 70)
    print(f"Token:        {signal.token[:12]}...")
    print(f"Side:         {signal.side}")
    print(f"Wallets:      {signal.wallet_count} unique wallets")
    print(f"Total Amount: {signal.total_amount:.4f}")
    print(f"Avg Amount:   {signal.avg_amount:.4f}")
    print(f"Time Window:  {signal.time_window_seconds:.1f} seconds")
    print(f"Confidence:   {signal.confidence:.0%}")
    print()
    print(f"Wallets involved:")
    for wallet in signal.wallets:
        print(f"  - {wallet[:12]}...")
    print("=" * 70)
    print()


async def run_hybrid(network: str = NETWORK_MAINNET):
    """Hybrid Mode: Real + Fake Trades"""
    global redundancy_engine
    
    print("=" * 60)
    print("🔀 HYBRID MODE - Mainnet + Fake Trades")
    print("=" * 60)
    print_network_info(network)
    print("=" * 60)
    
    # Wallets laden
    active_wallets = sync_wallets()
    wallet_addresses = [w.wallet for w in active_wallets]
    
    if not wallet_addresses:
        print("\n⚠️  WARNING: No active wallets found!")
        print("💡 Run: python main.py import")
        return
    
    print(f"[WalletSync] Active wallets: {len(wallet_addresses)}")
    
    # HTTP URL
    http_url = get_http_url(network)
    
    # Redundancy Engine
    redundancy_engine = RedundancyEngine(
        time_window_seconds=30,
        min_wallets=2,
        min_confidence=0.5
    )
    redundancy_engine.on_signal = handle_signal
    
    print()
    print("🧠 [Redundancy Engine] Activated")
    print(f"   Time Window: 30 seconds")
    print(f"   Min Wallets: 2")
    print(f"   Min Confidence: 50%")
    print()
    
    # Hybrid Source
    hybrid_source = HybridTradeSource(
        rpc_http_url=http_url,
        real_wallets=wallet_addresses,
        callback=handle_trade,
        poll_interval=2,
        inject_fake_trades=True,
        fake_trade_interval=20  # Alle 20s ein Pattern
    )
    
    print(f"[Hybrid] Listening with {len(wallet_addresses)} wallets")
    print(f"[Hybrid] Real polling every 2 seconds")
    print(f"[Hybrid] Fake pattern every 20 seconds")
    print()
    print("🟢 = Real Mainnet Trade")
    print("🔵 = Injected Fake Trade")
    print()
    print("💡 Watch for 🚨 SIGNAL alerts!")
    print("Press CTRL+C to stop")
    print()
    
    try:
        await hybrid_source.connect()
        
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[Hybrid] Stopping...")
        hybrid_source.stop()
        print("[Hybrid] Stopped")
    except Exception as e:
        print(f"\n[Hybrid] Error: {e}")
        hybrid_source.stop()


def run():
    """Entry point"""
    # Hybrid Mode läuft immer auf Mainnet
    network = NETWORK_MAINNET
    
    try:
        asyncio.run(run_hybrid(network))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
