"""
show_wallets.py - Zeigt alle Wallets aus axiom.db im Terminal an
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "axiom.db"

CATEGORY_ORDER  = ["OwnWallet", "ActiveWallet", "CandidateWallet", "ArchivedWallet"]
CATEGORY_LABELS = {
    "OwnWallet":       "OWN WALLET",
    "ActiveWallet":    "ACTIVE WALLETS",
    "CandidateWallet": "CANDIDATE WALLETS",
    "ArchivedWallet":  "ARCHIVED WALLETS",
}


def run():
    if not DB_PATH.exists():
        print(f"\n[Fehler] Datenbank nicht gefunden: {DB_PATH}")
        print("  Tipp: python import_wallets.py ausfuehren\n")
        return

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT wallet, category, active, COALESCE(source, '') FROM axiom_wallets ORDER BY category, wallet"
    ).fetchall()
    conn.close()

    if not rows:
        print("\n[Hinweis] Keine Wallets in der DB.")
        print("  Tipp: python import_wallets.py ausfuehren\n")
        return

    # Gruppieren
    grouped = {}
    for wallet, category, active, label in rows:
        grouped.setdefault(category, []).append((wallet, bool(active), label))

    total        = len(rows)
    total_active = sum(1 for _, _, a, _ in rows if a)

    print()
    print("=" * 64)
    print(f"  WALLETS IN BOT  ({total_active} aktiv / {total} gesamt)")
    print("=" * 64)

    for cat in CATEGORY_ORDER:
        if cat not in grouped:
            continue
        entries = grouped[cat]
        label   = CATEGORY_LABELS.get(cat, cat)
        active_count = sum(1 for _, a, _ in entries if a)
        print()
        print(f"  {label} ({active_count} aktiv / {len(entries)} gesamt)")
        print("  " + "-" * 60)
        for i, (addr, active, label) in enumerate(entries, 1):
            status   = "" if active else " [inaktiv]"
            label_str = f" [{label}]" if label else ""
            print(f"  {i:>2}.  {addr}{label_str}{status}")

    # Unbekannte Kategorien (Fallback)
    for cat, entries in grouped.items():
        if cat in CATEGORY_ORDER:
            continue
        print()
        print(f"  {cat.upper()} ({len(entries)})")
        print("  " + "-" * 60)
        for i, (addr, active, label) in enumerate(entries, 1):
            status    = "" if active else " [inaktiv]"
            label_str = f" [{label}]" if label else ""
            print(f"  {i:>2}.  {addr}{label_str}{status}")

    print()
    print("=" * 64)
    counts = {cat: sum(1 for _, a, _ in grouped.get(cat, []) if a)
              for cat in CATEGORY_ORDER}
    parts  = [f"{CATEGORY_LABELS.get(c, c)}: {counts[c]}"
              for c in CATEGORY_ORDER if c in grouped]
    print("  " + "  |  ".join(parts))
    print("=" * 64)
    print()
    print("  Tipp: python import_wallets.py  ->  DB aus axiom_wallets.json neu laden")
    print()
