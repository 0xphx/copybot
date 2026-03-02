"""
Verbose Wallet Import - Mit detailliertem Logging
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = "data/axiom.db"
JSON_PATH = "data/axiom_wallets.json"

print("="*70)
print("📦 WALLET IMPORT (VERBOSE)")
print("="*70)
print()

# 1. JSON laden
print(f"[1/4] Loading JSON: {JSON_PATH}")
with open(JSON_PATH, 'r', encoding='utf-8') as f:
    wallets = json.load(f)

print(f"✅ Found {len(wallets)} wallets in JSON")
print()

# Zeige erste 3
print("First 3 wallets:")
for i, w in enumerate(wallets[:3], 1):
    print(f"  {i}. {w['wallet'][:8]}... ({w['category']})")
print()

# 2. DB öffnen
print(f"[2/4] Opening database: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
print("✅ Database connected")
print()

# 3. Alte Wallets löschen
print("[3/4] Clearing old wallets...")
cursor.execute("SELECT COUNT(*) FROM axiom_wallets")
old_count = cursor.fetchone()[0]
print(f"   Old wallets in DB: {old_count}")

cursor.execute("DELETE FROM axiom_wallets")
print(f"✅ Deleted {old_count} old wallets")
print()

# 4. Neue Wallets einfügen
print("[4/4] Inserting new wallets...")
for i, entry in enumerate(wallets, 1):
    wallet = entry.get("wallet")
    category = entry.get("category")
    
    cursor.execute(
        "INSERT INTO axiom_wallets (wallet, category, active) VALUES (?, ?, 1)",
        (wallet, category)
    )
    
    if i <= 3 or i > len(wallets) - 3:
        print(f"   Inserted: {wallet[:8]}... ({category})")
    elif i == 4:
        print(f"   ... ({len(wallets) - 6} more) ...")

conn.commit()
print(f"✅ Inserted {len(wallets)} wallets")
print()

# 5. Verify
cursor.execute("SELECT COUNT(*) FROM axiom_wallets WHERE active = 1")
new_count = cursor.fetchone()[0]
print(f"[Verify] Active wallets in DB: {new_count}")

conn.close()

print()
print("="*70)
print("✅ IMPORT COMPLETE!")
print("="*70)
print()
print("Run: python debug_db.py to see all wallets")
print("Run: python main.py test to verify")
