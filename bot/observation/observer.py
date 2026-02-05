from observation.sources.base import TradeSource

class TradeObserver:
    def __init__(self, source: TradeSource | None = None):
        """
        source:
        - gesetzt → Pull-basierte Source (Fake, Replay)
        - None    → Push-basierte Source (Helius)
        """
        self.source = source

    def run(self):
        """
        Startet das Beobachten von Trades (Pull-Modell).
        """
        if not self.source:
            raise RuntimeError("No source set for pull-based observation")

        print("[Observer] Listening for trades (pull)...")

        for event in self.source.listen():
            self.handle_event(event)

    async def handle_event(self, event):
        print(
            f"[TradeEvent] {event.wallet} "
            f"{event.side.upper()} {event.amount} {event.token} "
            f"(source={event.source})"
        )


        # 🔜 nächste Schritte:
        # self.store(event)
        # self.pattern_engine.process(event)
