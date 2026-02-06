"""
Live Polling Runner mit Redundancy Engine
Erkennt koordinierte Trades zwischen Wallets
"""
import asyncio
import sys
from observation.sources.solana_polling import SolanaPollingSource
from config.network import get_http_url, print_network_info, NETWORK_DEVNET
from wallets.sync import sync_wallets
from pattern.redundancy import RedundancyEngine, TradeSignal


# Global Redundancy Engine
redundancy_engine = None


async def handle_trade(event):
    """Trade Event Handler mit Pattern Detection"""
    # Normale Trade Ausgabe
    print(
        f"[TradeEvent] {event.wallet[:8]}... "
        f"{event.side.upper()} {event.amount:.4f} {event.token[:8]}... "
        f"(source={event.source})"
    )
    
    # Pattern Detection
    if redundancy_engine:
        signal = redundancy_engine.process_trade(event)
        # Signal wird automatisch ausgegeben wenn erkannt


def handle_signal(signal: TradeSignal):
    """
    Handler für erkannte Signals
    Hier würde später die Execution passieren
    """
    print()
    print("=" * 70)
    print(f"🚨 STRONG {signal.side} SIGNAL DETECTED!")
    print("=" * 70)
    print(f"Token:        {signal.token}")
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
    
    # TODO: Hier würde Trade Execution passieren
    # if signal.confidence > 0.7:
    #     execute_copy_trade(signal)


async def run_live_polling(network: str = NETWORK_DEVNET):
    """Live Trading mit Polling + Redundancy Detection"""
    global redundancy_engine
    
    # Network Info
    print("=" * 60)
    print_network_info(network)
    print("=" * 60)
    
    # Wallets laden
    active_wallets = sync_wallets()
    wallet_addresses = [w.wallet for w in active_wallets]
    
    if not wallet_addresses:
        print("\n[WARNING]  WARNING: No active wallets found!")
        print("[INFO] Run: python main.py import")
        return
    
    print(f"[WalletSync] Active wallets: {len(wallet_addresses)}")
    
    # HTTP RPC URL
    http_url = get_http_url(network)
    
    # Redundancy Engine initialisieren
    redundancy_engine = RedundancyEngine(
        time_window_seconds=30,  # Trades innerhalb 30 Sekunden
        min_wallets=2,  # Mind. 2 Wallets müssen kaufen
        min_confidence=0.5  # Mind. 50% Confidence
    )
    redundancy_engine.on_signal = handle_signal
    
    print()
    print("🧠 [Redundancy Engine] Activated")
    print(f"   Time Window: 30 seconds")
    print(f"   Min Wallets: 2")
    print(f"   Min Confidence: 50%")
    print()
    
    # Polling Source erstellen
    polling_source = SolanaPollingSource(
        rpc_http_url=http_url,
        wallets=wallet_addresses,
        callback=handle_trade,
        poll_interval=2
    )
    
    print(f"[Live Polling] Listening with {len(wallet_addresses)} wallets")
    print(f"[Live Polling] Poll interval: 2 seconds")
    print()
    print("💡 Bot will alert when 2+ wallets buy the same token!")
    print("Press CTRL+C to stop")
    print()
    
    try:
        await polling_source.connect()
        
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[Live Polling] Stopping...")
        polling_source.stop()
        print("[Live Polling] Stopped")
    except Exception as e:
        print(f"\n[Live Polling] Error: {e}")
        polling_source.stop()


def run():
    """Entry point"""
    network = NETWORK_DEVNET
    if len(sys.argv) > 2:
        network = sys.argv[2].lower()
    
    try:
        asyncio.run(run_live_polling(network))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
