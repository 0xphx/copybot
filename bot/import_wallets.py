"""
Quick Wallet Import - Importiert neue Wallets in DB
"""
import sys
import os

# Füge parent directory zu path hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db
from axiom.loader import load_wallets_from_json

print("="*70)
print("📦 WALLET IMPORT")
print("="*70)
print()

# Init DB
init_db()
print("✅ Database initialized")

# Import Wallets
load_wallets_from_json("data/axiom_wallets.json")
print("✅ Wallets imported from axiom_wallets.json")

print()
print("="*70)
print("✅ IMPORT COMPLETE!")
print("="*70)
print()
print("Run 'python main.py test' to verify wallets")
