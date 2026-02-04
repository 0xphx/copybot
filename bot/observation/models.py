from dataclasses import dataclass

@dataclass
class TradeEvent:
    # Wallet, die den Trade ausgeführt hat
    wallet: str

    # Token Mint Address (oder Symbol später)
    token: str

    # buy oder sell
    side: str  # "buy" | "sell"

    # Menge des Tokens
    amount: float

    # Unix Timestamp
    timestamp: int

    # Quelle (debug / monitoring)
    source: str
