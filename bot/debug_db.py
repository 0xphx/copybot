"""
Debug Script - Zeigt Wallets in der DB
"""
import sqlite3

DB_PATH = "data/axiom.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("="*70)
print("🔍 DATABASE DEBUG")
print("="*70)
print()

# Zeige alle Wallets
cursor.execute("SELECT wallet, category, active FROM axiom_wallets")
wallets = cursor.fetchall()

print(f"📊 Total wallets in DB: {len(wallets)}")
print()

if wallets:
    print("Wallets:")
    for i, (wallet, category, active) in enumerate(wallets, 1):
        status = "✅" if active else "❌"
        print(f"{i:2}. {status} {wallet[:8]}... ({category})")
else:
    print("⚠️  No wallets found in database!")

print()
print("="*70)

conn.close()
