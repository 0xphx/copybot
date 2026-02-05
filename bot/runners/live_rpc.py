import asyncio

from wallets.sync import sync_wallets
from observation.observer import TradeObserver
from observation.sources.solana_rpc import SolanaRPCSource


def run():
    # 1. Wallets laden
    wallets = sync_wallets()
    wallet_addresses = [w.wallet for w in wallets]

    print(f"[WalletSync] Active wallets: {len(wallet_addresses)}")

    # 2. Observer erzeugen
    observer = TradeObserver()

    # 3. Source mit Callback verdrahten
    source = SolanaRPCSource(
        wallets=wallet_addresses,
        callback=observer.handle_event
    )

    print("[Live RPC] Listening to Solana WebSocket")

    # 4. Event Loop starten
    try:
        asyncio.run(source.listen())
    except KeyboardInterrupt:
        print("[Live RPC] Stopped by user")
