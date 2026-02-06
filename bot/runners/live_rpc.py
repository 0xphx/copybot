import asyncio
import sys
from wallets.sync import sync_wallets
from observation.observer import TradeObserver
from observation.sources.solana_rpc import SolanaRPCSource
from config.network import get_rpc_url, print_network_info, NETWORK_MAINNET, NETWORK_DEVNET

def run():
    """
    Startet Live RPC Observation mit konfigurierbarem Netzwerk.
    
    Usage:
        python main.py live_rpc           # Devnet (default)
        python main.py live_rpc mainnet   # Mainnet
        python main.py live_rpc devnet    # Devnet (explicit)
    """
    
    # Netzwerk aus Command Line Args lesen
    network = NETWORK_DEVNET  # Default
    if len(sys.argv) > 2:
        network = sys.argv[2].lower()
    
    # Netzwerk Info anzeigen
    print("=" * 60)
    print_network_info(network)
    print("=" * 60)
    
    # RPC URL für gewähltes Netzwerk
    rpc_url = get_rpc_url(network)
    
    # Wallets laden
    active_wallets = sync_wallets()
    wallet_addresses = [w.wallet for w in active_wallets]
    
    if not wallet_addresses:
        print("\n[WARNING]  WARNING: No active wallets found!")
        print("[INFO] Run: python main.py import")
        return

    # Observer und Source einrichten
    observer = TradeObserver()
    source = SolanaRPCSource(
        rpc_ws_url=rpc_url,
        wallets=wallet_addresses, 
        callback=observer.handle_event
    )

    print(f"\n[Live RPC] Listening with {len(wallet_addresses)} wallets")
    print("Press CTRL+C to stop\n")

    # Event Loop
    loop = asyncio.get_event_loop()
    task = loop.create_task(source.connect())

    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        print("\n[Live RPC] Stopping listener...")
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            print("[Live RPC] Listener cancelled cleanly")
        finally:
            loop.close()
