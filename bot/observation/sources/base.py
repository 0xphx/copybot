from abc import ABC, abstractmethod
from typing import Iterable
from observation.models import TradeEvent

class TradeSource(ABC):
    """
    Jede Datenquelle (Simulation, Helius, RPC)
    muss dieses Interface implementieren.
    """

    @abstractmethod
    def listen(self) -> Iterable[TradeEvent]:
        """
        Liefert kontinuierlich TradeEvents.
        """
        pass
