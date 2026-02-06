"""
Live Polling Runner - HTTP Polling statt WebSocket
"""
import asyncio
import sys
from observation.sources.solana_polling import SolanaPollingSource
from config.network import get_http_url, print_network_info, NETWORK_DEVNET
from wallets.sync import sync_wallets


async def handle_trade(event):
    """Trade Event Handler"""
    print(
        f"[TradeEvent] {event.wallet[:8]}... "
        f"{event.side.upper()} {event.amount:.4f} {event.token[:8]}... "
        f"(source={event.source})"
    )


async def run_live_polling(network: str = NETWORK_DEVNET):
    """
    Live Trading mit Polling-basierter Trade Detection
    
    Args:
        network: "mainnet", "devnet", "testnet"
    """
    
    # Network Info
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
    
    # HTTP RPC URL
    http_url = get_http_url(network)
    
    # Polling Source erstellen
    polling_source = SolanaPollingSource(
        rpc_http_url=http_url,
        wallets=wallet_addresses,
        callback=handle_trade,
        poll_interval=2  # Alle 2 Sekunden
    )
    
    print(f"[Live Polling] Listening with {len(wallet_addresses)} wallets")
    print(f"[Live Polling] Poll interval: 2 seconds")
    print("Press CTRL+C to stop")
    print()
    
    try:
        # Polling starten
        await polling_source.connect()
        
    except KeyboardInterrupt:
        print("\n[Live Polling] Stopping...")
        polling_source.stop()
        print("[Live Polling] Stopped")


def run():
    """Entry point"""
    # Netzwerk aus Command Line Args
    network = NETWORK_DEVNET
    if len(sys.argv) > 2:
        network = sys.argv[2].lower()
    
    asyncio.run(run_live_polling(network))


if __name__ == "__main__":
    run()
