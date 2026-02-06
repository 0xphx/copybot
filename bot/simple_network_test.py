"""
Simple Network Diagnostic - FIXED for websockets 14.x
"""
import socket
import sys
import os
from datetime import datetime

# Output in Datei umleiten
output_file = "network_report.txt"
original_stdout = sys.stdout
f = open(output_file, 'w', encoding='utf-8')
sys.stdout = f

try:
    print("=" * 60)
    print(f"[ADVANCED] NETWORK DIAGNOSTIC REPORT")
    print(f"Generated: {datetime.now()}")
    print(f"System: {os.name}")
    print("=" * 60)

    # Test 1: Basic Internet
    print("\n[TEST 1] Basic Internet Connectivity")
    print("-" * 60)
    
    test_hosts = [
        ("google.com", 443),
        ("github.com", 443),
        ("cloudflare.com", 443),
    ]
    
    internet_works = False
    for host, port in test_hosts:
        try:
            print(f"Testing {host}:{port}...", end=" ")
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            print("[OK] SUCCESS")
            internet_works = True
        except socket.timeout:
            print("[ERROR] TIMEOUT")
        except socket.gaierror as e:
            print(f"[ERROR] DNS FAILED: {e}")
        except ConnectionRefusedError:
            print("[ERROR] CONNECTION REFUSED")
        except Exception as e:
            print(f"[ERROR] ERROR: {type(e).__name__}: {e}")
    
    print(f"\nInternet Status: {'[OK] WORKING' if internet_works else '[ERROR] NOT WORKING'}")

    # Test 2: Solana RPC DNS Resolution
    print("\n[TEST 2] Solana RPC DNS Resolution")
    print("-" * 60)
    
    solana_hosts = [
        "api.mainnet-beta.solana.com",
        "api.devnet.solana.com",
        "api.testnet.solana.com",
    ]
    
    dns_works = False
    for host in solana_hosts:
        try:
            print(f"Resolving {host}...", end=" ")
            ip = socket.gethostbyname(host)
            print(f"[OK] {ip}")
            dns_works = True
        except socket.gaierror as e:
            print(f"[ERROR] FAILED: {e}")
        except Exception as e:
            print(f"[ERROR] ERROR: {e}")
    
    print(f"\nDNS Status: {'[OK] WORKING' if dns_works else '[ERROR] NOT WORKING'}")

    # Test 3: WebSocket Library
    print("\n[TEST 3] Python WebSocket Library")
    print("-" * 60)
    
    websockets_installed = False
    try:
        import websockets
        print(f"[OK] websockets installed (version: {websockets.__version__})")
        websockets_installed = True
    except ImportError:
        print("[ERROR] websockets NOT installed")
        print("   Fix: pip install websockets")

    # Test 4: Proxy Detection
    print("\n[TEST 4] Proxy Detection")
    print("-" * 60)
    
    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']
    proxy_found = False
    
    for var in proxy_vars:
        value = os.environ.get(var)
        if value:
            print(f"[WARNING]  {var} = {value}")
            proxy_found = True
    
    if not proxy_found:
        print("[OK] No proxy environment variables")
    else:
        print("\n[WARNING]  PROXY DETECTED - This may block WebSockets!")

    # Test 5: Advanced WebSocket Test (if library available)
    print("\n[TEST 5] WebSocket Connection Test")
    print("-" * 60)
    
    if websockets_installed:
        import asyncio
        
        async def test_ws(url, name):
            try:
                print(f"\nTesting {name}: {url}")
                print("  → Connecting...", end=" ")
                
                # websockets 14.x proper fix: open_timeout parameter
                ws = await websockets.connect(
                    url, 
                    ping_interval=20,
                    open_timeout=10
                )
                
                try:
                    print("[OK] CONNECTED")
                    
                    print("  → Sending ping...", end=" ")
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=5)
                    print("[OK] PONG RECEIVED")
                    
                    return True
                finally:
                    await ws.close()
                    
            except asyncio.TimeoutError:
                print("[ERROR] TIMEOUT")
                return False
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")
                return False
        
        async def run_tests():
            results = {}
            results['devnet'] = await test_ws("wss://api.devnet.solana.com", "Devnet")
            results['mainnet'] = await test_ws("wss://api.mainnet-beta.solana.com", "Mainnet")
            return results
        
        try:
            results = asyncio.run(run_tests())
            
            print("\n" + "-" * 60)
            if any(results.values()):
                print("[OK] At least one network is reachable!")
                for net, status in results.items():
                    if status:
                        print(f"   [OK] {net.upper()} - Working")
            else:
                print("[ERROR] No Solana networks reachable")
                print("   This might indicate firewall/antivirus blocking")
                
        except Exception as e:
            print(f"[ERROR] WebSocket tests failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("[WARNING]  Skipped - websockets library not installed")

    # Summary
    print("\n" + "=" * 60)
    print("[RESULTS] DIAGNOSTIC SUMMARY")
    print("=" * 60)
    
    issues = []
    recommendations = []
    
    if not internet_works:
        issues.append("[ERROR] No internet connectivity")
        recommendations.append("Check your internet connection")
    
    if not dns_works:
        issues.append("[ERROR] Cannot resolve Solana RPC domains")
        recommendations.append("Try: ipconfig /flushdns")
    
    if not websockets_installed:
        issues.append("[ERROR] websockets library missing")
        recommendations.append("Run: pip install websockets")
    
    if proxy_found:
        issues.append("[WARNING]  Proxy detected")
        recommendations.append("Try disabling proxy temporarily")
    
    if issues:
        print("\n[ISSUE] ISSUES FOUND:")
        for issue in issues:
            print(f"   {issue}")
        
        print("\n[INFO] RECOMMENDATIONS:")
        for i, rec in enumerate(recommendations, 1):
            print(f"   {i}. {rec}")
    else:
        print("\n[OK] Basic connectivity OK!")
        print("   If WebSocket tests failed, try:")
        print("   - Temporarily disable firewall")
        print("   - Temporarily disable antivirus")
        print("   - Use offline mode for testing")

    print("\n" + "=" * 60)
    print("[NOTE] NEXT STEPS:")
    print("=" * 60)
    
    if not internet_works:
        print("\n[ERROR] Fix internet connection first")
    elif not dns_works:
        print("\n[ERROR] Fix DNS resolution first")
    elif not websockets_installed:
        print("\n[ERROR] Install websockets first")
    else:
        print("\n[OK] Try these options:")
        print("\n   OPTION A: Offline Mode (ALWAYS works)")
        print("   → python main.py offline")
        print("\n   OPTION B: Test Network (check WebSocket)")
        print("   → python main.py test_network")
        print("\n   OPTION C: Live with Devnet")
        print("   → python main.py live_rpc devnet")

    print("\n" + "=" * 60)
    print("Report saved to: network_report.txt")
    print("=" * 60)

except Exception as e:
    print(f"\n\n[ERROR] CRITICAL ERROR: {e}")
    import traceback
    traceback.print_exc()

finally:
    sys.stdout = original_stdout
    f.close()
    
    print(f"\n[OK] Network diagnostic complete!")
    print(f" Report saved to: {os.path.abspath(output_file)}")
