"""
Paper Trading Portfolio - Virtuelles Kapital Management
1 Unit = 1 EUR
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Eine offene Position"""
    token: str
    entry_price_eur: float
    amount: float
    entry_time: datetime
    cost_eur: float
    trigger_wallets: List[str]  # Wallets die den Trade ausgelöst haben
    
    @property
    def current_value_eur(self) -> float:
        """Aktueller Wert (wird von außen aktualisiert)"""
        return self.amount * self.entry_price_eur
    
    def pnl_eur(self, current_price: float) -> float:
        """Profit/Loss in EUR"""
        return (current_price - self.entry_price_eur) * self.amount
    
    def pnl_percent(self, current_price: float) -> float:
        """Profit/Loss in %"""
        if self.entry_price_eur == 0:
            return 0.0
        return ((current_price - self.entry_price_eur) / self.entry_price_eur) * 100


@dataclass
class Trade:
    """Ein abgeschlossener Trade"""
    token: str
    side: str  # BUY / SELL
    price_eur: float
    amount: float
    value_eur: float
    timestamp: datetime
    trigger_wallets: List[str] = field(default_factory=list)
    pnl_eur: Optional[float] = None
    pnl_percent: Optional[float] = None


class PaperPortfolio:
    """Virtuelles Trading Portfolio"""
    
    def __init__(self, initial_capital_eur: float = 1000.0):
        self.initial_capital = initial_capital_eur
        self.cash_eur = initial_capital_eur
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Trade] = []
        self.position_size_percent = 0.20  # 20% des Kapitals pro Trade
        
        logger.info(f"[PaperPortfolio] Initialized with {initial_capital_eur:.2f} EUR")
    
    def get_total_value(self, token_prices: Dict[str, float]) -> float:
        """Gesamtwert: Cash + Positionen"""
        position_value = sum(
            pos.amount * token_prices.get(pos.token, pos.entry_price_eur)
            for pos in self.positions.values()
        )
        return self.cash_eur + position_value
    
    def get_available_capital(self) -> float:
        """Verfügbares Kapital für neue Trades"""
        return self.cash_eur
    
    def can_open_position(self, token: str, price_eur: float) -> bool:
        """Prüft ob Position eröffnet werden kann"""
        if token in self.positions:
            logger.debug(f"[PaperPortfolio] Position für {token} existiert bereits")
            return False
        
        required_capital = self.cash_eur * self.position_size_percent
        if required_capital < 1.0:  # Mindestens 1 EUR
            logger.debug(f"[PaperPortfolio] Nicht genug Kapital: {self.cash_eur:.2f} EUR")
            return False
        
        return True
    
    def open_position(
        self, 
        token: str, 
        price_eur: float, 
        trigger_wallets: List[str]
    ) -> Optional[Position]:
        """Eröffnet eine neue Position"""
        if not self.can_open_position(token, price_eur):
            return None
        
        # 20% des Cash für diesen Trade
        investment_eur = self.cash_eur * self.position_size_percent
        amount = investment_eur / price_eur
        
        position = Position(
            token=token,
            entry_price_eur=price_eur,
            amount=amount,
            entry_time=datetime.now(),
            cost_eur=investment_eur,
            trigger_wallets=trigger_wallets
        )
        
        self.positions[token] = position
        self.cash_eur -= investment_eur
        
        # Trade Historie
        trade = Trade(
            token=token,
            side="BUY",
            price_eur=price_eur,
            amount=amount,
            value_eur=investment_eur,
            timestamp=datetime.now(),
            trigger_wallets=trigger_wallets
        )
        self.trade_history.append(trade)
        
        logger.info(
            f"[PaperPortfolio] 🟢 BOUGHT {amount:.4f} {token[:8]}... "
            f"@ {price_eur:.4f} EUR = {investment_eur:.2f} EUR"
        )
        logger.info(f"[PaperPortfolio] Cash remaining: {self.cash_eur:.2f} EUR")
        
        return position
    
    def close_position(self, token: str, price_eur: float, reason: str = "") -> Optional[Trade]:
        """Schließt eine Position"""
        if token not in self.positions:
            logger.debug(f"[PaperPortfolio] Keine Position für {token}")
            return None
        
        position = self.positions[token]
        sell_value_eur = position.amount * price_eur
        pnl_eur = position.pnl_eur(price_eur)
        pnl_percent = position.pnl_percent(price_eur)
        
        # Cash zurück
        self.cash_eur += sell_value_eur
        
        # Trade Historie
        trade = Trade(
            token=token,
            side="SELL",
            price_eur=price_eur,
            amount=position.amount,
            value_eur=sell_value_eur,
            timestamp=datetime.now(),
            trigger_wallets=position.trigger_wallets,
            pnl_eur=pnl_eur,
            pnl_percent=pnl_percent
        )
        self.trade_history.append(trade)
        
        # Position entfernen
        del self.positions[token]
        
        emoji = "🟢" if pnl_eur >= 0 else "🔴"
        logger.info(
            f"[PaperPortfolio] {emoji} SOLD {trade.amount:.4f} {token[:8]}... "
            f"@ {price_eur:.4f} EUR = {sell_value_eur:.2f} EUR"
        )
        logger.info(
            f"[PaperPortfolio] P&L: {pnl_eur:+.2f} EUR ({pnl_percent:+.2f}%) {reason}"
        )
        logger.info(f"[PaperPortfolio] Cash: {self.cash_eur:.2f} EUR")
        
        return trade
    
    def has_position(self, token: str) -> bool:
        """Prüft ob Position existiert"""
        return token in self.positions
    
    def get_position(self, token: str) -> Optional[Position]:
        """Gibt Position zurück"""
        return self.positions.get(token)
    
    def get_statistics(self, token_prices: Dict[str, float]) -> dict:
        """Berechnet Performance Statistiken"""
        total_value = self.get_total_value(token_prices)
        total_pnl = total_value - self.initial_capital
        total_pnl_percent = (total_pnl / self.initial_capital) * 100
        
        # Trade Stats
        completed_trades = [t for t in self.trade_history if t.side == "SELL"]
        winning_trades = [t for t in completed_trades if t.pnl_eur and t.pnl_eur > 0]
        losing_trades = [t for t in completed_trades if t.pnl_eur and t.pnl_eur < 0]
        
        win_rate = (len(winning_trades) / len(completed_trades) * 100) if completed_trades else 0
        
        avg_win = sum(t.pnl_eur for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl_eur for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        return {
            "initial_capital": self.initial_capital,
            "current_cash": self.cash_eur,
            "positions_count": len(self.positions),
            "total_value": total_value,
            "total_pnl": total_pnl,
            "total_pnl_percent": total_pnl_percent,
            "trades_completed": len(completed_trades),
            "trades_winning": len(winning_trades),
            "trades_losing": len(losing_trades),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
        }
    
    def print_summary(self, token_prices: Dict[str, float]):
        """Gibt Portfolio Summary aus"""
        stats = self.get_statistics(token_prices)
        
        print("\n" + "="*70)
        print("📊 PAPER TRADING PORTFOLIO SUMMARY")
        print("="*70)
        print(f"Initial Capital:     {stats['initial_capital']:>12.2f} EUR")
        print(f"Current Cash:        {stats['current_cash']:>12.2f} EUR")
        print(f"Open Positions:      {stats['positions_count']:>12}")
        print(f"Total Value:         {stats['total_value']:>12.2f} EUR")
        print(f"Total P&L:           {stats['total_pnl']:>+12.2f} EUR ({stats['total_pnl_percent']:+.2f}%)")
        print("-"*70)
        print(f"Trades Completed:    {stats['trades_completed']:>12}")
        print(f"Winning Trades:      {stats['trades_winning']:>12}")
        print(f"Losing Trades:       {stats['trades_losing']:>12}")
        print(f"Win Rate:            {stats['win_rate']:>12.1f}%")
        print(f"Avg Win:             {stats['avg_win']:>+12.2f} EUR")
        print(f"Avg Loss:            {stats['avg_loss']:>+12.2f} EUR")
        print("="*70)
        
        if self.positions:
            print("\n📦 OPEN POSITIONS:")
            for token, pos in self.positions.items():
                current_price = token_prices.get(token, pos.entry_price_eur)
                pnl = pos.pnl_eur(current_price)
                pnl_pct = pos.pnl_percent(current_price)
                emoji = "🟢" if pnl >= 0 else "🔴"
                print(f"{emoji} {token[:8]}... | Entry: {pos.entry_price_eur:.4f} EUR | "
                      f"Current: {current_price:.4f} EUR | P&L: {pnl:+.2f} EUR ({pnl_pct:+.2f}%)")
        
        print()
    
    def save_to_file(self, filepath: str):
        """Speichert Portfolio in JSON"""
        data = {
            "initial_capital": self.initial_capital,
            "cash_eur": self.cash_eur,
            "positions": [
                {
                    "token": p.token,
                    "entry_price_eur": p.entry_price_eur,
                    "amount": p.amount,
                    "entry_time": p.entry_time.isoformat(),
                    "cost_eur": p.cost_eur,
                    "trigger_wallets": p.trigger_wallets
                }
                for p in self.positions.values()
            ],
            "trade_history": [
                {
                    "token": t.token,
                    "side": t.side,
                    "price_eur": t.price_eur,
                    "amount": t.amount,
                    "value_eur": t.value_eur,
                    "timestamp": t.timestamp.isoformat(),
                    "trigger_wallets": t.trigger_wallets,
                    "pnl_eur": t.pnl_eur,
                    "pnl_percent": t.pnl_percent
                }
                for t in self.trade_history
            ]
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"[PaperPortfolio] Saved to {filepath}")
