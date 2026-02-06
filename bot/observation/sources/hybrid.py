"""
Hybrid Trade Source
Kombiniert echte Mainnet Trades mit simulierten Test-Trades
Perfekt für Testing der Redundancy Engine!
"""
import asyncio
import random
from typing import List
from datetime import datetime

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
    ):
        # Echter Polling Source
        self.real_source = SolanaPollingSource(
            rpc_http_url=rpc_http_url,
            wallets=real_wallets,
            callback=self._handle_real_trade,
            poll_interval=poll_interval
        )
        
        self.real_wallets = real_wallets
        self.inject_fake_trades = inject_fake_trades
        self.fake_trade_interval = fake_trade_interval
        self.callback = callback
        self.running = False
        
        # Fake Token Pool für Tests
        self.fake_tokens = [
            "FakeToken1111111111111111111111111111111",
            "FakeToken2222222222222222222222222222222",
            "FakeToken3333333333333333333333333333333",
            "TestCoin1111111111111111111111111111111",
            "TestCoin2222222222222222222222222222222",
        ]
        
        print(f"[Hybrid] Real polling + Fake trade injection")
        print(f"[Hybrid] Fake pattern every {fake_trade_interval}s")
    
    
    async def connect(self):
        """Startet Hybrid Source"""
        self.running = True
        
        # Task 1: Real Polling
        real_task = asyncio.create_task(self.real_source.connect())
        
        # Task 2: Fake Trade Injection
        fake_task = None
        if self.inject_fake_trades:
            fake_task = asyncio.create_task(self._inject_fake_trades())
        
        try:
            if fake_task:
                await asyncio.gather(real_task, fake_task)
            else:
                await real_task
                
        except asyncio.CancelledError:
            self.running = False
            self.real_source.stop()
            raise
    
    
    async def _inject_fake_trades(self):
        """Injiziert fake koordinierte Trades"""
        print("[Hybrid] Fake trade injector started")
        
        while self.running:
            await asyncio.sleep(self.fake_trade_interval)
            
            if not self.running:
                break
            
            # Generiere koordiniertes Pattern
            await self._generate_fake_pattern()
    
    
    async def _generate_fake_pattern(self):
        """
        Generiert ein fake koordiniertes Trade Pattern
        
        Simuliert: 2-3 Wallets kaufen das gleiche Token
        """
        # Random Token aus Pool
        token = random.choice(self.fake_tokens)
        
        # Random 2-3 Wallets
        num_wallets = random.randint(2, min(3, len(self.real_wallets)))
        selected_wallets = random.sample(self.real_wallets, num_wallets)
        
        # Random Side
        side = random.choice(["BUY", "SELL"])
        
        # Base Amount mit Variation
        base_amount = random.uniform(100, 1000)
        
        print()
        print(f"💉 [Hybrid] Injecting FAKE {side} pattern:")
        print(f"   Token: {token[:8]}...")
        print(f"   Wallets: {num_wallets}")
        print()
        
        # Erstelle Trades mit kleinem Delay
        for i, wallet in enumerate(selected_wallets):
            # Kleine Amount Variation (±10%)
            amount = base_amount * random.uniform(0.9, 1.1)
            
            fake_trade = TradeEvent(
                wallet=wallet,
                token=token,
                side=side,
                amount=amount,
                source="hybrid_fake",
                raw_tx={"fake": True}
            )
            
            # Emit Trade
            if self.callback:
                if asyncio.iscoroutinefunction(self.callback):
                    await self.callback(fake_trade)
                else:
                    self.callback(fake_trade)
            
            # Kleiner Delay zwischen Trades (1-5s)
            if i < len(selected_wallets) - 1:
                await asyncio.sleep(random.uniform(1, 5))
    
    
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
    
    
    def listen(self):
        """Dummy für abstract base class"""
        raise NotImplementedError("Hybrid uses async connect()")
