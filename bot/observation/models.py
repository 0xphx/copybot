# observation/models.py
from dataclasses import dataclass
from typing import Any

@dataclass
class TradeEvent:
    wallet: str
    token: str
    side: str
    amount: float
    source: str = "solana_rpc"
    raw_tx: Any = None
