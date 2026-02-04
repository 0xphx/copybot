from fastapi import FastAPI, Request
from observation.sources.base import TradeSource
from observation.parser import parse_helius_swap

class HeliusTradeSource(TradeSource):
    def __init__(self, observer_callback):
        """
        observer_callback: Funktion, die TradeEvents entgegennimmt
        """
        self.app = FastAPI()
        self.observer_callback = observer_callback

        @self.app.post("/helius")
        async def helius_webhook(req: Request):
            payload = await req.json()

            # Helius sendet eine Liste von Events
            for event in payload:
                trade = parse_helius_swap(event)
                if trade:
                    self.observer_callback(trade)

            return {"status": "ok"}

    def listen(self):
        """
        Wird nicht genutzt – Helius pusht Events.
        """
        raise NotImplementedError("Helius uses webhooks, not polling")
