from wallets.sync import sync_wallets
from observation.observer import TradeObserver
from observation.sources.fake import FakeTradeSource

def run():
    wallets = sync_wallets()
    wallet_addresses = [w.wallet for w in wallets]

    source = FakeTradeSource(wallet_addresses)
    observer = TradeObserver(source)

    observer.run()
