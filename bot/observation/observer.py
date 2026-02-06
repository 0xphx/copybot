from observation.sources.base import TradeSource

class TradeObserver:
    def __init__(self, source: TradeSource | None = None):
        """
        source:
        - gesetzt → Pull-basierte Source (Fake, Replay)
        - None    → Push-basierte Source (Helius, RPC)
        """
        self.source = source

    def run(self):
        """
        Startet das Beobachten von Trades (Pull-Modell).
        Nur für synchrone Sources wie FakeTradeSource.
        """
        if not self.source:
            raise RuntimeError("No source set for pull-based observation")

        print("[Observer] Listening for trades (pull)...")

        for event in self.source.listen():
            # Synchrone Version für Fake/Test Sources
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            loop.run_until_complete(self.handle_event(event))

    async def handle_event(self, event):
        """
        Verarbeitet ein einzelnes TradeEvent.
        WICHTIG: Muss async sein für WebSocket-basierte Sources!
        """
        print(
            f"[TradeEvent] {event.wallet[:8]}... "
            f"{event.side.upper()} {event.amount:.4f} {event.token[:8]}... "
            f"(source={event.source})"
        )

        # 🔜 nächste Schritte:
        # await self.store(event)
        # await self.pattern_engine.process(event)
