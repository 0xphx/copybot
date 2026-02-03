#Models = Struktur

from dataclasses import dataclass
from typing import Optional

@dataclass
class AxiomWallet:
    wallet: str
    category: Optional[str] = None
    source: str = "axiom"
    active: bool = True
