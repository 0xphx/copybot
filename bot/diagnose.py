"""
Diagnose-Script für Copybot
Testet alle Komponenten systematisch
"""
import sys
import os

print("=" * 60)
print("[DIAGNOSTICS] COPYBOT DIAGNOSTICS")
print("=" * 60)

# Test 1: Python Version
print("\n[1] Python Version Check")
print(f"   Python: {sys.version}")
print(f"   Version Info: {sys.version_info}")

if sys.version_info < (3, 10):
    print("   [WARNING]  WARNING: Python 3.10+ recommended")
else:
    print("   [OK] Python version OK")

# Test 2: Dependencies
print("\n[2] Dependencies Check")
required = ["websockets", "sqlite3", "asyncio", "json", "dataclasses"]
for package in required:
    try:
        __import__(package)
        print(f"   [OK] {package}")
    except ImportError:
        print(f"   [ERROR] {package} - MISSING!")

# Test 3: Database Check
print("\n[3] Database Check")
db_path = "data/axiom.db"
if os.path.exists(db_path):
    print(f"   [OK] Database found: {db_path}")
    
    # Check DB content
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM axiom_wallets WHERE active = 1")
        count = cursor.fetchone()[0]
        print(f"   [OK] Active wallets in DB: {count}")
        
        cursor.execute("SELECT wallet, category FROM axiom_wallets LIMIT 3")
        wallets = cursor.fetchall()
        print(f"   [INFO] Sample wallets:")
        for wallet, cat in wallets:
            print(f"      - {wallet[:8]}... ({cat})")
            
    except sqlite3.OperationalError as e:
        print(f"   [ERROR] DB Error: {e}")
    finally:
        conn.close()
else:
    print(f"   [ERROR] Database NOT found: {db_path}")
    print(f"   [INFO] Run: python main.py import")

# Test 4: Module Imports
print("\n[4] Module Import Check")
modules_to_test = [
    "db.database",
    "axiom.loader",
    "wallets.sync",
    "observation.observer",
    "observation.sources.solana_rpc",
    "config.network",
]

for module in modules_to_test:
    try:
        __import__(module)
        print(f"   [OK] {module}")
    except Exception as e:
        print(f"   [ERROR] {module} - {e}")

# Test 5: Wallet Sync Test
print("\n[5] Wallet Sync Test")
try:
    from wallets.sync import sync_wallets
    wallets = sync_wallets()
    print(f"   [OK] Sync successful: {len(wallets)} wallets loaded")
    
    if wallets:
        print(f"   [INFO] First wallet: {wallets[0].wallet[:8]}... ({wallets[0].category})")
    else:
        print(f"   [WARNING]  No wallets found - check DB import")
        
except Exception as e:
    print(f"   [ERROR] Sync failed: {e}")

# Test 6: Network Configuration Test
print("\n[6] Network Configuration Test")
try:
    from config.network import get_rpc_url, NETWORK_MAINNET, NETWORK_DEVNET, NETWORK_TESTNET
    
    print(f"   [OK] Network config loaded")
    print(f"   [INFO] Mainnet: {get_rpc_url(NETWORK_MAINNET)}")
    print(f"   [INFO] Devnet:  {get_rpc_url(NETWORK_DEVNET)}")
    print(f"   [INFO] Testnet: {get_rpc_url(NETWORK_TESTNET)}")
    
except Exception as e:
    print(f"   [ERROR] Network config failed: {e}")

# Test 7: Network Connectivity Test (Quick)
print("\n[7] Network Connectivity Test")
try:
    import asyncio
    import websockets
    from config.network import NETWORK_DEVNET, get_rpc_url
    
    async def quick_test():
        url = get_rpc_url(NETWORK_DEVNET)
        try:
            async with websockets.connect(url, timeout=5) as ws:
                return True
        except Exception as e:
            return str(e)
    
    result = asyncio.run(quick_test())
    
    if result is True:
        print("   [OK] Devnet RPC reachable")
    else:
        print(f"   [WARNING]  Devnet RPC issue: {result}")
        print("   [INFO] Run: python main.py test_network (full test)")
        
except Exception as e:
    print(f"   [WARNING]  Network test skipped: {e}")

# Test 8: File Structure
print("\n[8] File Structure Check")
critical_files = [
    "main.py",
    "config/network.py",
    "observation/sources/solana_rpc.py",
    "observation/observer.py",
    "observation/models.py",
    "runners/live_rpc.py",
    "runners/scann_all.py",
    "runners/test_network.py",
    "data/axiom_wallets.json",
]

for file in critical_files:
    if os.path.exists(file):
        print(f"   [OK] {file}")
    else:
        print(f"   [ERROR] {file} - MISSING!")

print("\n" + "=" * 60)
print("[RESULTS] DIAGNOSIS COMPLETE")
print("=" * 60)

# Summary
print("\n[INFO] NEXT STEPS:")
print("   1. If DB missing → python main.py import")
print("   2. If no wallets → Check axiom_wallets.json")
print("   3. Test networks → python main.py test_network")
print("   4. If ready → python main.py live_rpc devnet")
print("   5. For mainnet → python main.py live_rpc mainnet")
print()
