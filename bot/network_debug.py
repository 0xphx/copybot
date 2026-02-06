"""
Advanced Network Diagnostics - FIXED for websockets 14.x
Testet verschiedene Aspekte der Netzwerkverbindung
"""
import socket
import ssl
import asyncio

print("=" * 60)
print("🔬 ADVANCED NETWORK DIAGNOSTICS")
print("=" * 60)

# Test 1: Basic Internet Connectivity
print("\n1️⃣ Basic Internet Connectivity")
test_hosts = [
    ("google.com", 443),
    ("cloudflare.com", 443),
    ("github.com", 443),
]

for host, port in test_hosts:
    try:
        print(f"   Testing {host}:{port}... ", end="", flush=True)
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        print("✅ OK")
    except socket.timeout:
        print("❌ TIMEOUT")
    except socket.gaierror:
        print("❌ DNS FAILED")
    except Exception as e:
        print(f"❌ ERROR: {e}")

# Test 2: DNS Resolution
print("\n2️⃣ DNS Resolution for Solana RPC")
solana_hosts = [
    "api.mainnet-beta.solana.com",
    "api.devnet.solana.com",
    "api.testnet.solana.com",
]

for host in solana_hosts:
    try:
        print(f"   Resolving {host}... ", end="", flush=True)
        ip = socket.gethostbyname(host)
        print(f"✅ {ip}")
    except socket.gaierror as e:
        print(f"❌ DNS FAILED: {e}")
    except Exception as e:
        print(f"❌ ERROR: {e}")

# Test 3: WebSocket Libraries
print("\n3️⃣ WebSocket Library Test")
try:
    import websockets
    print(f"   ✅ websockets installed (version: {websockets.__version__})")
except ImportError:
    print("   ❌ websockets NOT installed")
    print("   💡 Run: pip install websockets")

# Test 4: SSL/TLS Certificate Test
print("\n4️⃣ SSL/TLS Certificate Test")
for host in ["api.devnet.solana.com", "api.mainnet-beta.solana.com"]:
    try:
        print(f"   Testing SSL for {host}... ", end="", flush=True)
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                print(f"✅ OK (Protocol: {ssock.version()})")
    except ssl.SSLError as e:
        print(f"❌ SSL ERROR: {e}")
    except socket.timeout:
        print("❌ TIMEOUT")
    except Exception as e:
        print(f"❌ ERROR: {e}")

# Test 5: Direct WebSocket Connection (Detailed)
print("\n5️⃣ Detailed WebSocket Connection Test")

async def detailed_ws_test(url, name):
    print(f"\n   Testing {name}: {url}")
    try:
        print(f"   → Connecting... ", end="", flush=True)
        
        import websockets
        
        # websockets 14.x proper fix: use open_timeout
        ws = await websockets.connect(
            url, 
            ping_interval=20,
            open_timeout=10
        )
        
        try:
            print("✅ CONNECTED")
            
            print(f"   → Sending ping... ", end="", flush=True)
            pong_waiter = await ws.ping()
            await asyncio.wait_for(pong_waiter, timeout=5)
            print("✅ PONG RECEIVED")
            
            print(f"   → Testing JSON-RPC... ", end="", flush=True)
            test_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getHealth"
            }
            import json
            await ws.send(json.dumps(test_payload))
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"✅ Response: {response[:100]}...")
            
            return True
        finally:
            await ws.close()
            
    except asyncio.TimeoutError:
        print("\n   ❌ TIMEOUT - Connection took too long")
        return False
    except Exception as e:
        print(f"\n   ❌ ERROR: {type(e).__name__}: {e}")
        return False

async def test_all_ws():
    tests = [
        ("wss://api.devnet.solana.com", "Devnet"),
        ("wss://api.mainnet-beta.solana.com", "Mainnet"),
    ]
    
    results = {}
    for url, name in tests:
        results[name] = await detailed_ws_test(url, name)
    
    return results

try:
    results = asyncio.run(test_all_ws())
except Exception as e:
    print(f"\n   ❌ WebSocket test failed completely: {e}")
    results = {}

# Test 6: Proxy Detection
print("\n6️⃣ Proxy Detection")
import os

proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']
proxy_found = False

for var in proxy_vars:
    value = os.environ.get(var)
    if value:
        print(f"   ⚠️  {var}={value}")
        proxy_found = True

if not proxy_found:
    print("   ✅ No proxy environment variables set")
else:
    print("\n   💡 Proxy detected - this might block WebSocket connections")

# Test 7: Firewall Status
print("\n7️⃣ Firewall Status")
print("   ℹ️  You mentioned: Windows Firewall is DISABLED")
print("   ✅ This is good for testing WebSocket connections")

# Summary
print("\n" + "=" * 60)
print("📊 DIAGNOSTIC SUMMARY")
print("=" * 60)

issues = []

if not any(results.values()):
    issues.append("❌ No WebSocket connections successful")
    print("\n🔴 ISSUE: WebSocket connections failed")
    print("\n   Possible causes:")
    print("   1. Antivirus blocking (most likely)")
    print("   2. ISP/Network restrictions")
    print("   3. VPN active")
    print("   4. Solana RPC temporarily down")
else:
    print("\n✅ WebSocket connections SUCCESSFUL!")
    for name, status in results.items():
        if status:
            print(f"   ✅ {name} - Working")

if proxy_found:
    issues.append("⚠️  Proxy detected - might block connections")

print("\n💡 RECOMMENDED NEXT STEPS:")

if any(results.values()):
    print("\n   🎉 SUCCESS! Your system can connect to Solana!")
    print("\n   Try these commands:")
    print("   → python main.py test_network")
    print("   → python main.py live_rpc devnet")
else:
    print("\n   Since firewall is already disabled, try:")
    print("   1. Temporarily disable antivirus")
    print("   2. Disconnect VPN if active")
    print("   3. Try mobile hotspot / different network")
    print("   4. Use offline mode: python main.py offline")

print()
