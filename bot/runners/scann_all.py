import asyncio
import sys
from observation.observer import TradeObserver
from observation.sources.solana_rpc import SolanaRPCSource
from config.network import get_rpc_url, print_network_info, NETWORK_MAINNET, NETWORK_DEVNET

# Bekannte DEX Programme die wir beobachten wollen
DEX_PROGRAMS = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter Aggregator v6
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca Whirlpool
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
    "5quBtoiQqxF9Jv6KYKctB59NT3gtJD2Y65kdnB1Uev3h",  # Raydium Concentrated Liquidity
    "EewxydAPCCVuNEyrVN68PuSYdQ7wKn27V9Gjeoi8dy3S",  # Lifinity v2
}

def run():
    """
    Startet globalen Solana Log Scanner.
    
    Usage:
        python main.py scann_all           # Devnet (default)
        python main.py scann_all mainnet   # Mainnet (VIELE Events!)
        python main.py scann_all devnet    # Devnet (explicit)
    
    WARNUNG: Mainnet = TAUSENDE Events pro Sekunde!
    """
    
    # Netzwerk aus Command Line Args lesen
    network = NETWORK_DEVNET  # Default
    if len(sys.argv) > 2:
        network = sys.argv[2].lower()
    
    # Netzwerk Info anzeigen
    print("=" * 60)
    print("[ScanAll] Starting global Solana log scanner")
    print_network_info(network)
    print("=" * 60)
    
    # RPC URL für gewähltes Netzwerk
    rpc_url = get_rpc_url(network)
    
    if network == NETWORK_MAINNET:
        print("\n⚠️  WARNING: Mainnet scan produces THOUSANDS of events per second!")
        print("💡 Consider using Devnet for testing: python main.py scann_all devnet\n")
    
    print(f"[ScanAll] DEX Filters: {len(DEX_PROGRAMS)} programs")
    print("Press CTRL+C to stop\n")
    
    # Observer für Event-Handling
    observer = TradeObserver()
    
    # RPC Source im Scan-All Modus
    source = SolanaRPCSource(
        rpc_ws_url=rpc_url,
        wallets=[],              # keine Wallet-Filter
        callback=observer.handle_event,
        mode="all"               # globaler Modus
    )

    loop = asyncio.get_event_loop()
    task = loop.create_task(source.connect())

    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        print("\n[ScanAll] Stopping scanner...")
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            print("[ScanAll] Scanner stopped cleanly")
        finally:
            loop.close()
