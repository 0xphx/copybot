"""
Quick Fix Script - Automatische Problembehebung
Führt häufige Fixes automatisch aus
"""
import os
import sys
import sqlite3

print("=" * 60)
print("[AUTO-FIX] COPYBOT AUTO-FIX")
print("=" * 60)

def fix_database():
    """Stellt sicher dass DB initialisiert ist"""
    print("\n[1] Checking Database...")
    
    db_path = "data/axiom.db"
    
    if not os.path.exists(db_path):
        print("   [WARNING]  Database missing - creating...")
        from db.database import init_db
        init_db()
        print("   [OK] Database created")
    else:
        print("   [OK] Database exists")
    
    # Check if table exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='axiom_wallets'")
        if not cursor.fetchone():
            print("   [WARNING]  Table missing - creating...")
            from db.database import init_db
            init_db()
            print("   [OK] Table created")
        else:
            print("   [OK] Table exists")
    except Exception as e:
        print(f"   [ERROR] Error: {e}")
    finally:
        conn.close()

def fix_wallets():
    """Importiert Wallets wenn keine vorhanden"""
    print("\n[2] Checking Wallets...")
    
    db_path = "data/axiom.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM axiom_wallets")
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("   [WARNING]  No wallets found - importing...")
            from axiom.loader import load_wallets_from_json
            load_wallets_from_json("data/axiom_wallets.json")
            print("   [OK] Wallets imported")
        else:
            print(f"   [OK] {count} wallets in database")
            
        # Check if active
        cursor.execute("SELECT COUNT(*) FROM axiom_wallets WHERE active = 1")
        active_count = cursor.fetchone()[0]
        
        if active_count == 0 and count > 0:
            print("   [WARNING]  All wallets inactive - activating...")
            cursor.execute("UPDATE axiom_wallets SET active = 1")
            conn.commit()
            print("   [OK] Wallets activated")
        else:
            print(f"   [OK] {active_count} active wallets")
            
    except Exception as e:
        print(f"   [ERROR] Error: {e}")
    finally:
        conn.close()

def fix_pycache():
    """Löscht alte .pyc Dateien"""
    print("\n[3] Cleaning Cache...")
    
    removed = 0
    for root, dirs, files in os.walk("."):
        if "__pycache__" in dirs:
            pycache_path = os.path.join(root, "__pycache__")
            try:
                import shutil
                shutil.rmtree(pycache_path)
                removed += 1
            except Exception as e:
                pass
    
    if removed > 0:
        print(f"   [OK] Removed {removed} cache directories")
    else:
        print("   [OK] No cache to clean")

def verify_modules():
    """Prüft ob alle Module importierbar sind"""
    print("\n[4] Verifying Modules...")
    
    modules = [
        "db.database",
        "axiom.loader",
        "wallets.sync",
        "observation.observer",
        "observation.sources.solana_rpc",
    ]
    
    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"   [OK] {module}")
        except Exception as e:
            print(f"   [ERROR] {module}: {e}")
            all_ok = False
    
    return all_ok

def check_dependencies():
    """Prüft externe Dependencies"""
    print("\n[5] Checking Dependencies...")
    
    deps = ["websockets"]
    missing = []
    
    for dep in deps:
        try:
            __import__(dep)
            print(f"   [OK] {dep}")
        except ImportError:
            print(f"   [ERROR] {dep} - MISSING!")
            missing.append(dep)
    
    if missing:
        print(f"\n   [INFO] Install missing dependencies:")
        print(f"   pip install {' '.join(missing)}")
        return False
    
    return True

# Main Fix Routine
try:
    fix_database()
    fix_wallets()
    fix_pycache()
    modules_ok = verify_modules()
    deps_ok = check_dependencies()
    
    print("\n" + "=" * 60)
    
    if modules_ok and deps_ok:
        print("[OK] ALL FIXES APPLIED - SYSTEM READY")
        print("=" * 60)
        print("\n[INFO] Next steps:")
        print("   1. python diagnose.py    (full system check)")
        print("   2. python main.py live_rpc    (start live trading)")
    else:
        print("[WARNING]  SOME ISSUES REMAIN")
        print("=" * 60)
        print("\n[INFO] Next steps:")
        print("   1. Fix missing dependencies (see above)")
        print("   2. Run: python diagnose.py")
        print("   3. Check: TROUBLESHOOTING.md")
    
    print()

except Exception as e:
    print(f"\n[ERROR] ERROR during auto-fix: {e}")
    print("[INFO] Check TROUBLESHOOTING.md for manual fixes")
    import traceback
    traceback.print_exc()
