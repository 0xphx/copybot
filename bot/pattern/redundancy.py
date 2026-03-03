"""
Redundancy Engine - Erkennt koordinierte Trades
Wenn mehrere Wallets das gleiche Token kaufen = SIGNAL

Confidence Score berücksichtigt jetzt die historische Performance
der Wallets aus der wallet_performance.db.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import logging

from observation.models import TradeEvent

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Ein erkanntes Trade-Muster"""
    token: str
    side: str
    wallet_count: int
    wallets: List[str]
    total_amount: float
    avg_amount: float
    first_trade_time: datetime
    last_trade_time: datetime
    time_window_seconds: float
    confidence: float
    
    def __str__(self):
        return (
            f"🎯 SIGNAL: {self.side} {self.token[:8]}... "
            f"| {self.wallet_count} wallets "
            f"| Avg: {self.avg_amount:.2f} "
            f"| Window: {self.time_window_seconds:.1f}s "
            f"| Confidence: {self.confidence:.0%}"
        )


class RedundancyEngine:
    """Erkennt wenn mehrere Wallets koordiniert handeln"""
    
    def __init__(
        self,
        time_window_seconds: int = 30,
        min_wallets: int = 2,
        min_confidence: float = 0.5,
        wallet_tracker=None,  # Optional: WalletTracker Instanz für historische Confidence
    ):
        self.time_window = timedelta(seconds=time_window_seconds)
        self.min_wallets = min_wallets
        self.min_confidence = min_confidence
        self.wallet_tracker = wallet_tracker  # Kann None sein → kein DB-Lookup
        self.recent_trades: Dict[tuple, List[TradeEvent]] = defaultdict(list)
        self.on_signal = None
        
        tracker_status = "mit DB-Confidence" if wallet_tracker else "ohne DB-Confidence"
        logger.info(
            f"[RedundancyEngine] window={time_window_seconds}s, "
            f"min_wallets={min_wallets}, confidence={min_confidence:.0%}, "
            f"{tracker_status}"
        )
    
    def process_trade(self, trade: TradeEvent) -> Optional[TradeSignal]:
        """Verarbeitet Trade und prüft auf Patterns"""
        key = (trade.token, trade.side)
        self.recent_trades[key].append(trade)
        self._cleanup_old_trades()
        
        signal = self._detect_pattern(key)
        if signal:
            logger.info(f"[RedundancyEngine] {signal}")
            if self.on_signal:
                import asyncio
                import inspect
                if inspect.iscoroutinefunction(self.on_signal):
                    asyncio.create_task(self.on_signal(signal))
                else:
                    self.on_signal(signal)
        
        return signal
    
    def _cleanup_old_trades(self):
        """Entfernt alte Trades"""
        now = datetime.now()
        cutoff = now - self.time_window
        
        for key in list(self.recent_trades.keys()):
            self.recent_trades[key] = [
                t for t in self.recent_trades[key]
                if self._get_trade_time(t) > cutoff
            ]
            if not self.recent_trades[key]:
                del self.recent_trades[key]
    
    def _detect_pattern(self, key: tuple) -> Optional[TradeSignal]:
        """Erkennt Pattern"""
        token, side = key
        trades = self.recent_trades[key]
        
        if not trades:
            return None
        
        unique_wallets = set(t.wallet for t in trades)
        wallet_count = len(unique_wallets)
        
        if wallet_count < self.min_wallets:
            return None
        
        total_amount = sum(t.amount for t in trades)
        avg_amount = total_amount / len(trades)
        
        trade_times = [self._get_trade_time(t) for t in trades]
        first_time = min(trade_times)
        last_time = max(trade_times)
        window_seconds = (last_time - first_time).total_seconds()
        
        confidence = self._calculate_confidence(
            wallets=list(unique_wallets),
            wallet_count=wallet_count,
            trade_count=len(trades),
            window_seconds=window_seconds,
            amounts=[t.amount for t in trades]
        )
        
        if confidence < self.min_confidence:
            return None
        
        return TradeSignal(
            token=token,
            side=side,
            wallet_count=wallet_count,
            wallets=list(unique_wallets),
            total_amount=total_amount,
            avg_amount=avg_amount,
            first_trade_time=first_time,
            last_trade_time=last_time,
            time_window_seconds=window_seconds,
            confidence=confidence
        )
    
    def _calculate_confidence(
        self,
        wallets: List[str],
        wallet_count: int,
        trade_count: int,
        window_seconds: float,
        amounts: List[float]
    ) -> float:
        """
        Berechnet Confidence Score.
        
        Ohne WalletTracker (original Logik):
            - Wallet Count Score  (0–50 Punkte)
            - Timing Score        (10–30 Punkte)
            - Konsistenz Score    (0–20 Punkte)
        
        Mit WalletTracker (erweiterte Logik):
            - Historischer Wallet Performance Score ersetzt den einfachen
              Wallet Count Score. Gute Wallets = höherer Score.
        """
        
        if self.wallet_tracker is not None:
            return self._calculate_confidence_with_history(
                wallets, wallet_count, trade_count, window_seconds, amounts
            )
        else:
            return self._calculate_confidence_basic(
                wallet_count, trade_count, window_seconds, amounts
            )
    
    def _calculate_confidence_basic(
        self,
        wallet_count: int,
        trade_count: int,
        window_seconds: float,
        amounts: List[float]
    ) -> float:
        """Original Confidence Berechnung (ohne DB)"""
        wallet_score = min(wallet_count * 0.1, 0.5)
        
        if window_seconds < 5:
            time_score = 0.3
        elif window_seconds < 15:
            time_score = 0.2
        else:
            time_score = 0.1
        
        if amounts:
            avg = sum(amounts) / len(amounts)
            if avg > 0:
                variances = [(abs(a - avg) / avg) for a in amounts]
                avg_variance = sum(variances) / len(variances)
                consistency_score = max(0, 0.2 - (avg_variance * 0.2))
            else:
                consistency_score = 0.1
        else:
            consistency_score = 0.1
        
        return min(wallet_score + time_score + consistency_score, 1.0)
    
    def _calculate_confidence_with_history(
        self,
        wallets: List[str],
        wallet_count: int,
        trade_count: int,
        window_seconds: float,
        amounts: List[float]
    ) -> float:
        """
        Hybrid Confidence: Signal wird ausgelöst wenn mehrere gut bewertete
        Wallets denselben Coin kaufen. Wallet-Qualität ist der Kernfaktor.

        Gewichtung:
          55% – Historischer Wallet Confidence Score (Durchschnitt aller beteiligten Wallets)
          25% – Wallet Count (mehr übereinstimmende gute Wallets = stärkeres Signal)
          15% – Timing (Koordination, weniger kritisch als früher)
           5% – Konsistenz der Trade-Größen (bei Memecoins kaum aussagekräftig)
        """
        
        import math

        # Wallet Confidence Scores aus DB holen
        conf_map = self.wallet_tracker.get_confidence_map(wallets)

        # 1. History Score (55%)
        # Durchschnitt der Wallet-Confidence-Scores aller beteiligten Wallets.
        # Neutrale Wallets (0.5) dämpfen das Signal – kein Fallback mehr.
        # Nur wenn alle Wallets echte (nicht-neutrale) Scores haben ist das Signal stark.
        avg_hist_confidence = sum(conf_map.values()) / len(conf_map) if conf_map else 0.5
        history_score = avg_hist_confidence * 0.55

        # 2. Wallet Count Score (25%) – logarithmisch
        # Mehr übereinstimmende gute Wallets = stärkeres Signal
        # 2 Wallets = 0.11, 3 = 0.16, 5 = 0.20, 10 = 0.25
        count_score = min(math.log(wallet_count + 1, 11), 1.0) * 0.25

        # 3. Timing Score (15%)
        # Wie koordiniert haben die Wallets gekauft?
        # Weniger kritisch als bisher – ein gutes Wallet das 15s später kauft ist trotzdem wertvoll
        if window_seconds < 5:
            time_score = 0.15
        elif window_seconds < 15:
            time_score = 0.10
        elif window_seconds < 30:
            time_score = 0.05
        else:
            time_score = 0.02

        # 4. Konsistenz Score (5%)
        # Bei Memecoins variieren Kaufmengen stark – kaum aussagekräftig
        if amounts and len(amounts) > 1:
            avg = sum(amounts) / len(amounts)
            if avg > 0:
                variances = [(abs(a - avg) / avg) for a in amounts]
                avg_variance = sum(variances) / len(variances)
                consistency_score = max(0, 0.05 - (avg_variance * 0.05))
            else:
                consistency_score = 0.02
        else:
            consistency_score = 0.02

        total = history_score + time_score + count_score + consistency_score

        logger.debug(
            f"[RedundancyEngine] Confidence breakdown: "
            f"history={history_score:.2f} (avg_wallet={avg_hist_confidence:.2f}) "
            f"count={count_score:.2f} timing={time_score:.2f} "
            f"consistency={consistency_score:.2f} → total={total:.2f}"
        )
        
        return min(total, 1.0)
    
    def _get_trade_time(self, trade: TradeEvent) -> datetime:
        """Trade Timestamp"""
        return datetime.now()
    
    def get_recent_patterns(self) -> List[TradeSignal]:
        """Gibt aktive Patterns zurück"""
        patterns = []
        for key in self.recent_trades.keys():
            signal = self._detect_pattern(key)
            if signal:
                patterns.append(signal)
        return patterns
    
    def reset(self):
        """Löscht History"""
        self.recent_trades.clear()
        logger.info("[RedundancyEngine] History cleared")
