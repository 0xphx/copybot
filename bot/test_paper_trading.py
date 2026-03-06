"""
Quick Test - Prüft ob alle Module importierbar sind
"""
import sys

print("Testing Paper Trading System...")
print()

# Test 1: Trading Module
print("[1/5] Testing trading module...")
try:
    from trading.portfolio import PaperPortfolio, Position, Trade
    from trading.price_oracle import PriceOracle, MockPriceOracle
    from trading.engine import PaperTradingEngine
    print(" Trading module OK")
except Exception as e:
    print(f" Trading module failed: {e}")
    sys.exit(1)

# Test 2: Observation Module
print("[2/5] Testing observation module...")
try:
    from observation.models import TradeEvent
    from observation.sources.hybrid import HybridTradeSource
    print(" Observation module OK")
except Exception as e:
    print(f" Observation module failed: {e}")
    sys.exit(1)

# Test 3: Pattern Module
print("[3/5] Testing pattern module...")
try:
    from pattern.redundancy import RedundancyEngine, TradeSignal
    print(" Pattern module OK")
except Exception as e:
    print(f" Pattern module failed: {e}")
    sys.exit(1)

# Test 4: Config Module
print("[4/5] Testing config module...")
try:
    from config.network import RPC_HTTP_ENDPOINTS, NETWORK_MAINNET
    print(" Config module OK")
except Exception as e:
    print(f" Config module failed: {e}")
    sys.exit(1)

# Test 5: Wallets Module
print("[5/5] Testing wallets module...")
try:
    from wallets.sync import sync_wallets
    print(" Wallets module OK")
except Exception as e:
    print(f" Wallets module failed: {e}")
    sys.exit(1)

# Test 6: Paper Trading Runners
print("[6/6] Testing paper trading runners...")
try:
    from runners import paper_trading
    from runners import paper_mainnet
    print(" Paper trading runners OK")
except Exception as e:
    print(f" Paper trading runners failed: {e}")
    sys.exit(1)

print()
print("="*60)
print(" ALL MODULES OK - Ready for Paper Trading!")
print("="*60)
print()
print("Available commands:")
print("  python main.py paper           # Hybrid (Mainnet + Fake)")
print("  python main.py paper_mainnet   # Pure Mainnet (No fakes)")
print()
print("Recommended: Start with 'paper' for fast testing!")
