import asyncio
from wallets.sync import sync_wallets
from observation.observer import TradeObserver
from observation.sources.solana_rpc import SolanaRPCSource

def run():
    active_wallets = sync_wallets()
    wallet_addresses = [w.wallet for w in active_wallets]

    observer = TradeObserver()
    source = SolanaRPCSource(wallets=wallet_addresses, callback=observer.handle_event)

    print(f"[Live RPC] Listening to Solana WebSocket with {len(wallet_addresses)} wallets")

    loop = asyncio.get_event_loop()
    task = loop.create_task(source.connect())

    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        print("\n[Live RPC] Stopping listener...")
        task.cancel()
        # Task beenden, CancelledError intern catchen
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            print("[Live RPC] Listener cancelled cleanly")
        finally:
            loop.close()
