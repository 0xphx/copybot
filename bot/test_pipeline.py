"""
Test Script - Simuliert einen Trade Event
Testet die komplette Pipeline ohne echte WebSocket Verbindung
"""
import asyncio
from observation.observer import TradeObserver
from observation.models import TradeEvent

async def test_trade_pipeline():
    """Testet ob Observer und Event-Verarbeitung funktionieren"""
    
    print("=" * 60)
    print("🧪 TRADE PIPELINE TEST")
    print("=" * 60)
    
    # Observer erstellen
    observer = TradeObserver()
    
    # Test Event 1: BUY
    print("\n1️⃣ Testing BUY Event...")
    buy_event = TradeEvent(
        wallet="DnhJdhSKVXbF1z5a4fosyBrxyjtwEZzQCRBYTqbZC4e3",
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        side="BUY",
        amount=100.5,
        source="test"
    )
    
    try:
        await observer.handle_event(buy_event)
        print("   ✅ BUY event processed")
    except Exception as e:
        print(f"   ❌ BUY event failed: {e}")
    
    # Test Event 2: SELL
    print("\n2️⃣ Testing SELL Event...")
    sell_event = TradeEvent(
        wallet="CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o",
        token="So11111111111111111111111111111111111111112",
        side="SELL",
        amount=50.25,
        source="test"
    )
    
    try:
        await observer.handle_event(sell_event)
        print("   ✅ SELL event processed")
    except Exception as e:
        print(f"   ❌ SELL event failed: {e}")
    
    # Test Event 3: Mit Timestamp
    print("\n3️⃣ Testing Event with Timestamp...")
    import time
    timed_event = TradeEvent(
        wallet="G9u3uBMCstdf9gatnPbYteKFnczGFPEnbWaq4bnuC2Ub",
        token="7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
        side="BUY",
        amount=1000.0,
        source="test",
        timestamp=time.time()
    )
    
    try:
        await observer.handle_event(timed_event)
        print("   ✅ Timed event processed")
        print(f"   📅 Timestamp: {timed_event.timestamp}")
    except Exception as e:
        print(f"   ❌ Timed event failed: {e}")
    
    print("\n" + "=" * 60)
    print("✅ PIPELINE TEST COMPLETE")
    print("=" * 60)
    print("\nIf all tests passed, the system is ready for live data!")
    print("Next: python main.py live_rpc")
    print()

if __name__ == "__main__":
    asyncio.run(test_trade_pipeline())
