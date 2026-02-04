import asyncio
from wallets.sync import sync_wallets
from observation.observer import TradeObserver
from observation.sources.solana_rpc import SolanaRPCSource


def run():
    wallets = sync_wallets()
    wallet_addresses = [w.wallet for w in wallets]

    observer = TradeObserver()

    source = SolanaRPCSource(
        wallets=wallet_addresses,
        callback=observer.handle_event
    )

    print("[Live RPC] Listening to Solana WebSocket")

    asyncio.run(source.listen())
