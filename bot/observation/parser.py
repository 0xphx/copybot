import time
from observation.models import TradeEvent

def parse_helius_swap(event: dict) -> TradeEvent | None:
    """
    Extrahiert einen TradeEvent aus einem Helius Swap-Event.
    Gibt None zurück, wenn es kein relevanter Trade ist.
    """

    # Sicherheitschecks
    if event.get("type") != "SWAP":
        return None

    wallet = event.get("source")
    token_in = event["swap"]["tokenInputs"][0]
    token_out = event["swap"]["tokenOutputs"][0]

    # Heuristik:
    # Wenn SOL ausgegeben wird → Buy
    side = "buy" if token_in["mint"] == "So11111111111111111111111111111111111111112" else "sell"

    return TradeEvent(
        wallet=wallet,
        token=token_out["mint"],
        side=side,
        amount=float(token_out["amount"]),
        timestamp=int(time.time()),
        source="helius"
    )
