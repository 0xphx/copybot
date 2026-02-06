"""
Offline Mode - Simuliert Solana Trades ohne Netzwerkverbindung
Nützlich für Testing wenn kein Netzwerk verfügbar ist
"""
import asyncio
import time
import random
from observation.observer import TradeObserver
from observation.models import TradeEvent
from wallets.sync import sync_wallets

# Bekannte Token Mints für Simulation
TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
}

class OfflineTradeSimulator:
    """Simuliert realistische Trades ohne Netzwerk"""
    
    def __init__(self, wallets: list[str], interval: float = 2.0):
        self.wallets = wallets
        self.interval = interval
        self.observer = TradeObserver()
    
    async def generate_trade(self) -> TradeEvent:
        """Generiert einen realistischen Trade"""
        wallet = random.choice(self.wallets)
        token_name = random.choice(list(TOKENS.keys()))
        token_mint = TOKENS[token_name]
        side = random.choice(["BUY", "SELL"])
        
        # Realistische Beträge
        if token_name == "SOL":
            amount = round(random.uniform(0.1, 10.0), 4)
        elif token_name == "USDC":
            amount = round(random.uniform(10, 1000), 2)
        else:
            amount = round(random.uniform(100, 100000), 2)
        
        return TradeEvent(
            wallet=wallet,
            token=token_mint,
            side=side,
            amount=amount,
            source="offline_simulator",
            timestamp=time.time()
        )
    
    async def run(self):
        """Startet die Simulation"""
        print("=" * 60)
        print("🏠 OFFLINE MODE - Trade Simulator")
        print("=" * 60)
        print(f"\n[Offline] Simulating trades for {len(self.wallets)} wallets")
        print(f"[Offline] Interval: {self.interval}s")
        print(f"[Offline] Tokens: {', '.join(TOKENS.keys())}")
        print("\nPress CTRL+C to stop\n")
        
        trade_count = 0
        
        try:
            while True:
                trade = await self.generate_trade()
                await self.observer.handle_event(trade)
                
                trade_count += 1
                
                # Alle 10 Trades: Statistik
                if trade_count % 10 == 0:
                    print(f"\n[Offline] 📊 {trade_count} trades simulated")
                
                await asyncio.sleep(self.interval)
                
        except KeyboardInterrupt:
            print(f"\n\n[Offline] Stopped after {trade_count} trades")

def run():
    """Entry point für Offline Mode"""
    
    # Versuche Wallets zu laden
    try:
        active_wallets = sync_wallets()
        wallet_addresses = [w.wallet for w in active_wallets]
        
        if not wallet_addresses:
            print("⚠️  No wallets in DB - using demo wallets")
            wallet_addresses = [
                "Demo1111111111111111111111111111111111111",
                "Demo2222222222222222222222222222222222222",
                "Demo3333333333333333333333333333333333333",
            ]
    except Exception as e:
        print(f"⚠️  Could not load wallets: {e}")
        print("Using demo wallets...")
        wallet_addresses = [
            "Demo1111111111111111111111111111111111111",
            "Demo2222222222222222222222222222222222222",
            "Demo3333333333333333333333333333333333333",
        ]
    
    simulator = OfflineTradeSimulator(wallet_addresses, interval=2.0)
    asyncio.run(simulator.run())

if __name__ == "__main__":
    run()
