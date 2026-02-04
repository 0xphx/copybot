import uvicorn
from observation.observer import TradeObserver
from observation.sources.helius import HeliusTradeSource


def run():
    """
    Startet den Live-Helius Webhook Listener
    """

    # Observer ohne Source (Push-Modell!)
    observer = TradeObserver()

    # Helius Source bekommt Callback
    helius_source = HeliusTradeSource(observer.handle_event)

    print("[Live] Starting Helius webhook listener on http://localhost:8000/helius")

    uvicorn.run(
        helius_source.app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
