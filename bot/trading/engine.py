"""
Paper Trading Engine - Managed automatisches Trading
Reagiert auf Signals und Trade Events
"""
import asyncio
import logging
from typing import Optional, Dict, Set
from datetime import datetime

from pattern.redundancy import TradeSignal
from observation.models import TradeEvent
from trading.portfolio import PaperPortfolio
from trading.price_oracle import PriceOracle

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """Automatischer Paper Trading Bot"""
    
    def __init__(
        self, 
        portfolio: PaperPortfolio,
        price_oracle: PriceOracle,
        polling_source=None,
        price_update_interval: int = 10,
        stop_loss_percent: float = -15.0,    # -15% → automatischer Verkauf
        take_profit_percent: float = 50.0,   # +50% → automatischer Verkauf
    ):
        self.portfolio = portfolio
        self.oracle = price_oracle
        self.polling_source = polling_source
        self.price_update_interval = price_update_interval
        self.stop_loss_percent = stop_loss_percent
        self.take_profit_percent = take_profit_percent
        
        # Tracking welche Wallets zu welchen Positionen gehören
        self.position_trigger_wallets: Dict[str, Set[str]] = {}
        
        # Price Update Loop
        self.price_update_task = None
        self.last_prices: Dict[str, float] = {}  # Token -> Last Price
        
        logger.info("[PaperTradingEngine] Initialized")
    
    async def on_buy_signal(self, signal: TradeSignal):
        """Reagiert auf BUY Signal – öffnet Position"""
        token = signal.token
        
        logger.info(
            f"[TradingEngine] 🎯 BUY SIGNAL: {token[:8]}... "
            f"from {signal.wallet_count} wallets"
        )
        
        if self.portfolio.has_position(token):
            logger.info(f"[TradingEngine] ⏭️  Position already exists for {token[:8]}...")
            return
        
        price_eur = await self.oracle.get_price_eur(token)
        if price_eur is None:
            logger.warning(f"[TradingEngine] ❌ No price available for {token[:8]}...")
            return
        
        if not self.portfolio.can_open_position(token, price_eur):
            logger.warning(f"[TradingEngine] ❌ Not enough capital for {token[:8]}...")
            return
        
        position = self.portfolio.open_position(
            token=token,
            price_eur=price_eur,
            trigger_wallets=signal.wallets
        )
        
        if position:
            self.position_trigger_wallets[token] = set(signal.wallets)
            self.last_prices[token] = price_eur
            
            if self.price_update_task is None or self.price_update_task.done():
                self.price_update_task = asyncio.create_task(self._price_update_loop())
            
            if self.polling_source:
                if hasattr(self.polling_source, 'start_watching_wallets'):
                    self.polling_source.start_watching_wallets(signal.wallets)
                if hasattr(self.polling_source, 'pause_fake_trades'):
                    self.polling_source.pause_fake_trades()
            
            logger.info(
                f"[TradingEngine] ✅ Opened position for {token[:8]}... "
                f"@ {price_eur:.6f} EUR"
            )
    
    async def on_trade_event(self, trade: TradeEvent):
        """
        Reagiert auf einzelne Trade Events.
        Schließt Position wenn ein Trigger-Wallet exakt diesen Token verkauft.
        """
        token = trade.token
        wallet = trade.wallet
        side = trade.side
        
        if side != "SELL":
            return
        
        if not self.portfolio.has_position(token):
            return
        
        trigger_wallets = self.position_trigger_wallets.get(token, set())
        if wallet not in trigger_wallets:
            logger.debug(
                f"[TradingEngine] Wallet {wallet[:8]}... sold {token[:8]}... "
                f"but is not a trigger wallet → ignoring"
            )
            return
        
        price_eur = await self.oracle.get_price_eur(token, skip_cache=True)
        if price_eur is None:
            logger.warning(f"[TradingEngine] ❌ No price for exit on {token[:8]}...")
            return
        
        await self._close_position(
            token=token,
            price_eur=price_eur,
            reason=f"WALLET_SOLD",
            trigger_label=f"{wallet[:8]}... sold"
        )
    
    async def _close_position(self, token: str, price_eur: float, reason: str, trigger_label: str):
        """Zentraler Ort zum Schließen einer Position mit SELL-Box."""
        position = self.portfolio.positions.get(token)
        if not position:
            return
        
        entry_price = position.entry_price_eur
        pnl_pct = ((price_eur - entry_price) / entry_price) * 100
        pnl_eur = (price_eur - entry_price) * position.amount
        
        # Emoji für Ergebnis
        result_emoji = "✅" if pnl_eur >= 0 else "🛑"
        
        print()
        print("="*70)
        print(f"{result_emoji} SELL SIGNAL DETECTED! [{reason}]")
        print("="*70)
        print(f"Token:        {token[:15]}...")
        print(f"Trigger:      {trigger_label}")
        print(f"Entry Price:  {entry_price:.8f} EUR")
        print(f"Exit Price:   {price_eur:.8f} EUR")
        print(f"P&L:          {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%)")
        print(f"Quantity:     {position.amount:.4f}")
        print("="*70)
        print()
        
        trade_result = self.portfolio.close_position(
            token=token,
            price_eur=price_eur,
            reason=f"({trigger_label})"
        )
        
        if trade_result:
            if token in self.position_trigger_wallets:
                del self.position_trigger_wallets[token]
            if token in self.last_prices:
                del self.last_prices[token]
            
            if not self.portfolio.positions:
                if self.polling_source:
                    if hasattr(self.polling_source, 'stop_watching_wallets'):
                        self.polling_source.stop_watching_wallets()
                    if hasattr(self.polling_source, 'resume_fake_trades'):
                        self.polling_source.resume_fake_trades()
            
            logger.info(
                f"[TradingEngine] ✅ Closed {token[:8]}... @ {price_eur:.8f} EUR "
                f"| P&L: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%)"
            )
    
    async def _price_update_loop(self):
        """
        🔄 PRICE UPDATE LOOP
        - Zeigt alle N Sekunden Price Updates
        - Prüft Stop-Loss und Take-Profit
        """
        logger.info(
            f"[PriceMonitor] Started (updates every {self.price_update_interval}s | "
            f"SL: {self.stop_loss_percent:+.0f}% | TP: {self.take_profit_percent:+.0f}%)"
        )
        
        try:
            while True:
                await asyncio.sleep(self.price_update_interval)
                
                if not self.portfolio.positions:
                    logger.info("[PriceMonitor] No open positions - stopping")
                    break
                
                for token in list(self.portfolio.positions.keys()):
                    try:
                        current_price = await self.oracle.get_price_eur(token, skip_cache=True)
                        if current_price is None:
                            continue
                        
                        position = self.portfolio.positions[token]
                        entry_price = position.entry_price_eur
                        
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        pnl_eur = (current_price - entry_price) * position.amount
                        
                        last_price = self.last_prices.get(token, entry_price)
                        price_change_pct = ((current_price - last_price) / last_price) * 100 if last_price > 0 else 0
                        
                        emoji = "📈" if pnl_eur > 0 else "📉" if pnl_eur < 0 else "➡️"
                        
                        print(
                            f"{emoji} [PriceMonitor] {token[:8]}... @ {current_price:.8f} EUR "
                            f"| P&L: {pnl_eur:+.2f} EUR ({pnl_pct:+.2f}%) "
                            f"| Last {self.price_update_interval}s: {price_change_pct:+.2f}%"
                        )
                        
                        self.last_prices[token] = current_price
                        
                        # ─── STOP-LOSS ────────────────────────────────────────
                        if pnl_pct <= self.stop_loss_percent:
                            logger.warning(
                                f"[StopLoss] 🛑 {token[:8]}... hit stop-loss "
                                f"({pnl_pct:.1f}% ≤ {self.stop_loss_percent:.0f}%)"
                            )
                            await self._close_position(
                                token=token,
                                price_eur=current_price,
                                reason="STOP_LOSS",
                                trigger_label=f"Stop-Loss triggered @ {pnl_pct:.1f}%"
                            )
                            continue  # Token aus Positionen entfernt, nächstes
                        
                        # ─── TAKE-PROFIT ──────────────────────────────────────
                        if pnl_pct >= self.take_profit_percent:
                            logger.info(
                                f"[TakeProfit] 🎯 {token[:8]}... hit take-profit "
                                f"({pnl_pct:.1f}% ≥ {self.take_profit_percent:.0f}%)"
                            )
                            await self._close_position(
                                token=token,
                                price_eur=current_price,
                                reason="TAKE_PROFIT",
                                trigger_label=f"Take-Profit triggered @ {pnl_pct:.1f}%"
                            )
                            continue
                    
                    except Exception as e:
                        logger.error(f"[PriceMonitor] Error updating {token[:8]}: {e}")
                        continue
        
        except asyncio.CancelledError:
            logger.info("[PriceMonitor] Stopped (cancelled)")
        except Exception as e:
            logger.error(f"[PriceMonitor] Loop crashed: {e}")
    
    async def check_open_positions(self):
        """Prüft offene Positionen – für externe Aufrufe"""
        if not self.portfolio.positions:
            return
        
        for token in list(self.portfolio.positions.keys()):
            position = self.portfolio.positions[token]
            current_price = await self.oracle.get_price_eur(token)
            if current_price is None:
                continue
            
            pnl = position.pnl_eur(current_price)
            pnl_pct = position.pnl_percent(current_price)
            
            if abs(pnl_pct) >= 5:
                emoji = "📈" if pnl > 0 else "📉"
                logger.info(
                    f"[TradingEngine] {emoji} {token[:8]}... "
                    f"P&L: {pnl:+.2f} EUR ({pnl_pct:+.2f}%)"
                )
    
    def get_portfolio_summary(self) -> dict:
        token_prices = {
            token: pos.entry_price_eur
            for token, pos in self.portfolio.positions.items()
        }
        return self.portfolio.get_statistics(token_prices)
    
    async def print_summary(self):
        token_prices = {}
        for token in self.portfolio.positions.keys():
            price = await self.oracle.get_price_eur(token)
            token_prices[token] = price if price else self.portfolio.positions[token].entry_price_eur
        self.portfolio.print_summary(token_prices)
    
    async def stop(self):
        """Stoppt alle Background Tasks"""
        if self.price_update_task and not self.price_update_task.done():
            self.price_update_task.cancel()
            try:
                await self.price_update_task
            except asyncio.CancelledError:
                pass
