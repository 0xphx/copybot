# observation/models.py
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

@dataclass
class TradeEvent:
    wallet: str
    token: str
    side: str
    amount: float
    source: str = "solana_rpc"
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    raw_tx: Any = None
