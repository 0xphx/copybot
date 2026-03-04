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
        stop_loss_percent: float = -50.0,
        take_profit_percent: float = 100.0,
        wallet_tracker=None,   # Optional: für strategie-basierte SL/TP
    ):
        self.portfolio = portfolio
        self.oracle = price_oracle
        self.polling_source = polling_source
        self.price_update_interval = price_update_interval
        self.stop_loss_percent = stop_loss_percent    # globaler Fallback
        self.take_profit_percent = take_profit_percent  # globaler Fallback
        self.wallet_tracker = wallet_tracker

        # Tracking welche Wallets zu welchen Positionen gehören
        self.position_trigger_wallets: Dict[str, Set[str]] = {}

        # Strategie-basierte SL/TP pro Token
        # token → (stop_loss_pct, take_profit_pct)
        self.position_sl_tp: Dict[str, tuple] = {}

        # Inaktivitäts-Tracking pro Token
        # token → letzter Preis bei dem eine Änderung festgestellt wurde
        self.position_last_changed_price: Dict[str, float] = {}
        # token → Zeitpunkt der letzten Preisänderung
        self.position_last_changed_time: Dict[str, float] = {}

        # Price Update Loop
        self.price_update_task = None
        self.last_prices: Dict[str, float] = {}

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

            # SL/TP aus Wallet-Strategie ableiten
            if self.wallet_tracker:
                sl, tp = self.wallet_tracker.get_sl_tp_for_wallets(signal.wallets)
                logger.info(
                    f"[TradingEngine] Strategy SL/TP for {token[:8]}...: "
                    f"SL={sl:.0f}% TP=+{tp:.0f}% "
                    f"(wallets: {[w[:8] for w in signal.wallets]})"
                )
            else:
                sl, tp = self.stop_loss_percent, self.take_profit_percent
            self.position_sl_tp[token] = (sl, tp)

            # Inaktivitäts-Timer starten
            import time
            self.position_last_changed_price[token] = price_eur
            self.position_last_changed_time[token]  = time.monotonic()
            
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
            # Tag-Abbau: nur wenn Close NICHT durch Inaktivität ausgelöst wurde
            if reason != "INACTIVITY" and self.wallet_tracker:
                trigger_wallets = list(self.position_trigger_wallets.get(token, set()))
                for w in trigger_wallets:
                    current_tags = self.wallet_tracker.get_inactivity_tags(w)
                    if current_tags > 0:
                        self.wallet_tracker.remove_inactivity_tag(w)

            if token in self.position_trigger_wallets:
                del self.position_trigger_wallets[token]
            if token in self.last_prices:
                del self.last_prices[token]
            if token in self.position_sl_tp:
                del self.position_sl_tp[token]
            if token in self.position_last_changed_price:
                del self.position_last_changed_price[token]
            if token in self.position_last_changed_time:
                del self.position_last_changed_time[token]
            
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

                        import time

                        # ─── INAKTIVITÄT ─────────────────────────────────────
                        if current_price == self.position_last_changed_price.get(token):
                            trigger_wallets = list(self.position_trigger_wallets.get(token, set()))
                            timeout = (
                                self.wallet_tracker.get_inactivity_timeout(trigger_wallets)
                                if self.wallet_tracker else 600
                            )
                            inactive_secs = time.monotonic() - self.position_last_changed_time.get(token, time.monotonic())
                            if inactive_secs >= timeout:
                                logger.warning(
                                    f"[Inactivity] ⏱️ {token[:8]}... no price change for "
                                    f"{inactive_secs/60:.1f} min (limit {timeout//60} min) – closing"
                                )
                                # Tags auf alle Trigger-Wallets
                                if self.wallet_tracker:
                                    for w in trigger_wallets:
                                        tags = self.wallet_tracker.add_inactivity_tag(w)
                                        logger.info(f"[Inactivity] Tag {w[:8]}... → {tags} tag(s)")
                                await self._close_position(
                                    token=token,
                                    price_eur=current_price,
                                    reason="INACTIVITY",
                                    trigger_label=f"Inactivity {inactive_secs/60:.1f} min (limit {timeout//60} min)"
                                )
                                continue
                        else:
                            # Preis hat sich geändert – Timer zurücksetzen
                            self.position_last_changed_price[token] = current_price
                            self.position_last_changed_time[token]  = time.monotonic()

                        # SL/TP: positions-spezifisch oder globaler Fallback
                        sl, tp = self.position_sl_tp.get(
                            token,
                            (self.stop_loss_percent, self.take_profit_percent)
                        )

                        # ─── STOP-LOSS ────────────────────────────────────────
                        if pnl_pct <= sl:
                            logger.warning(
                                f"[StopLoss] 🛑 {token[:8]}... hit stop-loss "
                                f"({pnl_pct:.1f}% <= {sl:.0f}%)"
                            )
                            await self._close_position(
                                token=token,
                                price_eur=current_price,
                                reason="STOP_LOSS",
                                trigger_label=f"Stop-Loss @ {pnl_pct:.1f}% (limit {sl:.0f}%)"
                            )
                            continue

                        # ─── TAKE-PROFIT ──────────────────────────────────────
                        if pnl_pct >= tp:
                            logger.info(
                                f"[TakeProfit] 🎯 {token[:8]}... hit take-profit "
                                f"({pnl_pct:.1f}% >= +{tp:.0f}%)"
                            )
                            await self._close_position(
                                token=token,
                                price_eur=current_price,
                                reason="TAKE_PROFIT",
                                trigger_label=f"Take-Profit @ +{pnl_pct:.1f}% (limit +{tp:.0f}%)"
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
