import time
from observation.models import TradeEvent
from observation.sources.base import TradeSource

class FakeTradeSource(TradeSource):
    def __init__(self, wallets: list[str]):
        self.wallets = wallets

    def listen(self):
        """
        Simuliert Trades für Test & Entwicklung.
        """
        while True:
            for wallet in self.wallets:
                yield TradeEvent(
                    wallet=wallet,
                    token="FAKE_TOKEN",
                    side="buy",
                    amount=100,
                    timestamp=int(time.time()),
                    source="fake"
                )
                time.sleep(1)
