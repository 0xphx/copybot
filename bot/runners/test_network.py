"""
Network Test Runner - FIXED for websockets 14.x
"""
import asyncio
import websockets
from config.network import RPC_ENDPOINTS, NETWORK_MAINNET, NETWORK_DEVNET, NETWORK_TESTNET

async def test_network(name: str, url: str):
    """Testet ob ein Netzwerk erreichbar ist"""
    try:
        print(f"Testing {name}... ", end="", flush=True)
        
        # websockets 14.x: use open_timeout parameter
        ws = await websockets.connect(
            url, 
            ping_interval=20,
            open_timeout=10
        )
        
        try:
            # Teste mit ping
            pong_waiter = await ws.ping()
            await asyncio.wait_for(pong_waiter, timeout=5)
            print("[OK] ONLINE")
            return True
        finally:
            await ws.close()
            
    except asyncio.TimeoutError:
        print("[ERROR] TIMEOUT")
        return False
    except Exception as e:
        print(f"[ERROR] ERROR: {type(e).__name__}")
        return False

async def test_all_networks():
    """Testet alle verfügbaren Netzwerke"""
    print("=" * 60)
    print("[NETWORK] SOLANA NETWORK CONNECTIVITY TEST")
    print("=" * 60)
    print()
    
    results = {}
    
    for network, url in RPC_ENDPOINTS.items():
        results[network] = await test_network(network.upper(), url)
    
    print()
    print("=" * 60)
    print("[RESULTS] RESULTS")
    print("=" * 60)
    
    available = [k for k, v in results.items() if v]
    unavailable = [k for k, v in results.items() if not v]
    
    if available:
        print(f"\n[OK] Available networks ({len(available)}):")
        for net in available:
            print(f"   - {net}")
    
    if unavailable:
        print(f"\n[ERROR] Unavailable networks ({len(unavailable)}):")
        for net in unavailable:
            print(f"   - {net}")
    
    print()
    
    # Recommendations
    if NETWORK_DEVNET in available:
        print("[INFO] RECOMMENDATION: Use Devnet for testing")
        print("   python main.py live_rpc devnet")
    elif NETWORK_MAINNET in available:
        print("[INFO] RECOMMENDATION: Mainnet available but use with caution")
        print("   python main.py live_rpc mainnet")
    else:
        print("[WARNING]  WARNING: No networks available!")
        print("   Possible causes:")
        print("   - Firewall blocking WebSockets")
        print("   - Antivirus blocking connections")
        print("   - Corporate network restrictions")
        print()
        print("   Try: python main.py offline (works without network)")
    
    print()

def run():
    """Entry point für network test runner"""
    asyncio.run(test_all_networks())

if __name__ == "__main__":
    run()
