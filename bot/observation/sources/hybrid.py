"""
Hybrid Trade Source
Kombiniert echte Mainnet Trades mit simulierten Test-Trades
Perfekt für Testing der Redundancy Engine!
"""
import asyncio
import random
from typing import List, Set
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from observation.models import TradeEvent
from observation.sources.solana_polling import SolanaPollingSource


class HybridTradeSource:
    """
    Hybrid Source: Echte Trades + Fake Trades
    
    Features:
    - Läuft auf echtem Mainnet
    - Injiziert zusätzliche Test-Trades
    - Simuliert koordinierte Käufe
    """
    
    def __init__(
        self,
        rpc_http_url: str,
        real_wallets: List[str],
        callback=None,
        poll_interval: int = 2,
        inject_fake_trades: bool = True,
        fake_trade_interval: int = 20,  # Alle 20s ein fake pattern
        fast_poll_interval: float = 0.5,  # Schnelles Polling bei offenen Positionen
    ):
        # Echter Polling Source
        self.real_source = SolanaPollingSource(
            rpc_http_url=rpc_http_url,
            wallets=real_wallets,
            callback=self._handle_real_trade,
            poll_interval=poll_interval,
            fast_poll_interval=fast_poll_interval
        )
        
        self.real_wallets = real_wallets
        self.inject_fake_trades = inject_fake_trades
        self.fake_trade_interval = fake_trade_interval
        self.callback = callback
        self.running = False
        self.pause_fake_injector = False  # Pausiere Fake Trades bei offener Position
        self.active_trigger_wallets: Set[str] = set()  # Wallets die zur Position gehören
        
        # Fake Token Pool für Tests
        self.fake_tokens = [
            "FakeToken1111111111111111111111111111111",
            "FakeToken2222222222222222222222222222222",
            "FakeToken3333333333333333333333333333333",
            "TestCoin1111111111111111111111111111111",
            "TestCoin2222222222222222222222222222222",
        ]
        
        # Track fake BUY trades um später SELL zu generieren
        self.fake_buy_trades = {}  # {token: [(wallet, amount, timestamp), ...]}
        
        print(f"[Hybrid] Real polling + Fake trade injection")
        print(f"[Hybrid] Fake pattern every {fake_trade_interval}s")
    
    
    async def connect(self):
        """Startet Hybrid Source"""
        self.running = True
        
        # Task 1: Real Polling
        real_task = asyncio.create_task(self.real_source.connect())
        
        # Task 2: Fake BUY Injection
        # Task 3: Fake SELL Generation
        fake_buy_task = None
        fake_sell_task = None
        
        if self.inject_fake_trades:
            fake_buy_task = asyncio.create_task(self._inject_fake_buys())
            fake_sell_task = asyncio.create_task(self._inject_fake_sells())
        
        try:
            tasks = [real_task]
            if fake_buy_task:
                tasks.append(fake_buy_task)
            if fake_sell_task:
                tasks.append(fake_sell_task)
            
            await asyncio.gather(*tasks)
                
        except asyncio.CancelledError:
            self.running = False
            self.real_source.stop()
            raise
    
    
    async def _inject_fake_buys(self):
        """Injiziert fake BUY Patterns"""
        print("[Hybrid] Fake BUY injector started")
        print("[Hybrid] First BUY pattern in 5 seconds...")
        
        # Erste BUY Pattern nach 5s statt 20s!
        await asyncio.sleep(5)
        
        while self.running:
            if not self.running:
                break
            
            # Pausiere nur BUY Generation wenn Position offen ist
            if self.pause_fake_injector:
                await asyncio.sleep(1)  # Kurze Pause, dann erneut prüfen
                continue
            
            # Generiere koordiniertes BUY Pattern
            await self._generate_fake_buy_pattern()
            
            # Warte fake_trade_interval bis zum nächsten BUY
            await asyncio.sleep(self.fake_trade_interval)
    
    async def _inject_fake_sells(self):
        """Generiert fake SELL Patterns (läuft parallel, IMMER aktiv!)"""
        print("[Hybrid] Fake SELL generator started")
        
        # Warte etwas bevor erste SELLs generiert werden
        await asyncio.sleep(35)  # Nach 35s (5s BUY + 30s wait)
        
        while self.running:
            if not self.running:
                break
            
            # Generiere SELLs für alte BUYs (IMMER, auch wenn pausiert!)
            if self.fake_buy_trades:
                await self._generate_fake_sell_if_old()
            
            # Prüfe alle 5 Sekunden
            await asyncio.sleep(5)
    
    
    async def _generate_fake_buy_pattern(self):
        """
        Generiert ein fake koordiniertes Trade Pattern
        
        Simuliert: 2-3 Wallets kaufen das gleiche Token
        """
        # Random Token aus Pool
        token = random.choice(self.fake_tokens)
        
        # Random 2-3 Wallets
        num_wallets = random.randint(2, min(3, len(self.real_wallets)))
        selected_wallets = random.sample(self.real_wallets, num_wallets)
        
        # Base Amount mit Variation
        base_amount = random.uniform(100, 1000)
        
        print()
        print(f"💉 [Hybrid] Injecting FAKE BUY pattern:")
        print(f"   Token: {token[:8]}...")
        print(f"   Wallets: {num_wallets}")
        print()
        
        # Track für spätere SELLs
        if token not in self.fake_buy_trades:
            self.fake_buy_trades[token] = []
        
        # Erstelle BUY Trades mit kleinem Delay
        for i, wallet in enumerate(selected_wallets):
            # Prüfe ob pausiert wurde (während vorherigem Delay)
            if self.pause_fake_injector:
                logger.info(f"[Hybrid] ⚠️ BUY pattern INTERRUPTED after {i} trades (paused)")
                break
            
            # Kleine Amount Variation (±10%)
            amount = base_amount * random.uniform(0.9, 1.1)
            
            fake_trade = TradeEvent(
                wallet=wallet,
                token=token,
                side="BUY",
                amount=amount,
                source="hybrid_fake",
                raw_tx={"fake": True}
            )
            
            # Track BUY
            self.fake_buy_trades[token].append({
                "wallet": wallet,
                "amount": amount,
                "timestamp": datetime.now()
            })
            
            # Emit Trade
            if self.callback:
                if asyncio.iscoroutinefunction(self.callback):
                    await self.callback(fake_trade)
                else:
                    self.callback(fake_trade)
            
            # Kleiner Delay zwischen Trades (1-5s)
            if i < len(selected_wallets) - 1:
                await asyncio.sleep(random.uniform(1, 5))
    
    
    async def _generate_fake_sell_if_old(self):
        """
        Prüft ob es alte BUYs gibt (>30s) und generiert SELLs
        """
        now = datetime.now()
        
        for token, buys in list(self.fake_buy_trades.items()):
            if not buys:
                continue
            
            # Prüfe ältesten BUY
            oldest = min(buy["timestamp"] for buy in buys)
            age_seconds = (now - oldest).total_seconds()
            
            # Wenn älter als 30s → verkaufe 1-2 Wallets
            if age_seconds > 30:
                await self._generate_fake_sell_pattern(token)
    
    async def _generate_fake_sell_pattern(self, token: str = None):
        """
        Generiert SELL Trades für einige der fake BUY Trades
        Simuliert: 1-2 Lead-Wallets verkaufen
        
        Wichtig: Verkauft nur Trigger-Wallets wenn Position offen ist!
        """
        if not self.fake_buy_trades:
            return
        
        # Wähle Token
        if token is None:
            available_tokens = [t for t in self.fake_buy_trades.keys() if self.fake_buy_trades[t]]
            if not available_tokens:
                return
            token = random.choice(available_tokens)
        
        if token not in self.fake_buy_trades or not self.fake_buy_trades[token]:
            return
        
        buys = self.fake_buy_trades[token]
        
        # Wenn Position offen: Nur Trigger-Wallets können verkaufen!
        if self.active_trigger_wallets:
            # Filtere nur Trigger-Wallets
            trigger_buys = [b for b in buys if b["wallet"] in self.active_trigger_wallets]
            
            if not trigger_buys:
                # Keine Trigger-Wallets haben dieses Token gekauft
                return
            
            # Verkaufe 1-2 Trigger-Wallets
            num_sells = min(random.randint(1, 2), len(trigger_buys))
            sells = random.sample(trigger_buys, num_sells)
        else:
            # Keine Position offen: Random Wallets
            num_sells = min(random.randint(1, 2), len(buys))
            sells = random.sample(buys, num_sells)
        
        print()
        print(f"💉 [Hybrid] Injecting FAKE SELL pattern:")
        print(f"   Token: {token[:8]}...")
        print(f"   Wallets: {num_sells}")
        if self.active_trigger_wallets:
            print(f"   🎯 TRIGGER WALLETS (will close position!)")
        print()
        
        for sell_info in sells:
            fake_trade = TradeEvent(
                wallet=sell_info["wallet"],
                token=token,
                side="SELL",
                amount=sell_info["amount"],
                source="hybrid_fake",
                raw_tx={"fake": True}
            )
            
            # Emit Trade
            if self.callback:
                if asyncio.iscoroutinefunction(self.callback):
                    await self.callback(fake_trade)
                else:
                    self.callback(fake_trade)
            
            # Entferne aus Tracking
            self.fake_buy_trades[token].remove(sell_info)
            
            await asyncio.sleep(random.uniform(0.5, 2))
        
        # Cleanup leere Token
        if not self.fake_buy_trades[token]:
            del self.fake_buy_trades[token]
    
    async def _handle_real_trade(self, trade: TradeEvent):
        """Handler für echte Trades"""
        # Markiere als "real"
        trade.source = "mainnet_real"
        
        # Forward to main callback
        if self.callback:
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(trade)
            else:
                self.callback(trade)
    
    
    def stop(self):
        """Stoppt Hybrid Source"""
        self.running = False
        self.real_source.stop()
        print("[Hybrid] Stopped")
    
    def pause_fake_trades(self):
        """Pausiert Fake Trade Generation"""
        self.pause_fake_injector = True
        logger.info("[Hybrid] ⏸️ Fake trade injector PAUSED")
    
    def resume_fake_trades(self):
        """Setzt Fake Trade Generation fort"""
        self.pause_fake_injector = False
        logger.info("[Hybrid] ▶️ Fake trade injector RESUMED")
    
    def start_watching_wallets(self, wallets: list[str]):
        """Leitet an real_source weiter und trackt Trigger-Wallets"""
        # Merke welche Wallets zur Position gehören
        self.active_trigger_wallets = set(wallets)
        logger.info(f"[Hybrid] 🎯 Tracking {len(wallets)} trigger wallets for SELL generation")
        
        if hasattr(self.real_source, 'start_watching_wallets'):
            self.real_source.start_watching_wallets(wallets)
    
    def stop_watching_wallets(self):
        """Leitet an real_source weiter und löscht Trigger-Wallets"""
        # Keine Trigger-Wallets mehr
        self.active_trigger_wallets.clear()
        logger.info("[Hybrid] 🎯 Trigger wallets cleared")
        
        if hasattr(self.real_source, 'stop_watching_wallets'):
            self.real_source.stop_watching_wallets()
    
    def listen(self):
        """Dummy für abstract base class"""
        raise NotImplementedError("Hybrid uses async connect()")
