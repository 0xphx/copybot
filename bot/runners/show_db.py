"""
Show DB - Gibt die wallet_performance.db im Terminal aus
"""
import sqlite3
import sys
from datetime import datetime

DB_PATH = "data/wallet_performance.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def show_wallet_stats(filter_min_trades: int = 0, sort_by: str = "confidence"):
    """Zeigt alle Wallet Stats"""
    conn = connect()
    cursor = conn.cursor()

    order_map = {
        "confidence": "confidence_score DESC",
        "pnl":        "total_pnl_eur DESC",
        "winrate":    "win_rate DESC",
        "trades":     "total_trades DESC",
    }
    order = order_map.get(sort_by, "confidence_score DESC")

    cursor.execute(f"""
        SELECT * FROM wallet_stats
        WHERE total_trades >= ?
        ORDER BY {order}
    """, (filter_min_trades,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("  (keine Einträge)")
        return

    print(f"  {'#':<4} {'Wallet':<18} {'Trades':>6} {'Win%':>6} {'P&L EUR':>10} {'Avg P&L':>9} {'Confidence':>22}  {'Updated'}")
    print("  " + "─"*100)

    for i, r in enumerate(rows, 1):
        conf   = r['confidence_score']
        wr_str   = f"{r['win_rate']*100:.0f}%"
        pnl_str  = f"{r['total_pnl_eur']:+.2f}"
        avg_str  = f"{r['avg_pnl_eur']:+.2f}"
        updated  = r['last_updated'][:16]

        if conf >= 0.7:
            emoji = "🟢"
        elif conf >= 0.5:
            emoji = "🟡"
        else:
            emoji = "🔴"

        print(
            f"  {i:<4} {emoji} {r['wallet'][:16]:<16}  "
            f"{r['total_trades']:>5}x  "
            f"{wr_str:>5}  "
            f"{pnl_str:>9} EUR  "
            f"{avg_str:>8} EUR  "
            f"{conf:>6.2f}  "
            f"{updated}"
        )

    print()
    print(f"  Gesamt: {len(rows)} Wallets")
    if filter_min_trades > 0:
        print(f"  Filter: min. {filter_min_trades} Trades")


def show_sessions():
    """Zeigt alle Sessions"""
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            session_id,
            COUNT(*) as total_trades,
            COUNT(CASE WHEN side = 'SELL' THEN 1 END) as sells,
            COUNT(DISTINCT wallet) as wallets,
            ROUND(SUM(CASE WHEN side = 'SELL' AND pnl_eur IS NOT NULL THEN pnl_eur ELSE 0 END), 2) as total_pnl,
            MIN(timestamp) as started,
            MAX(timestamp) as ended
        FROM wallet_trades
        GROUP BY session_id
        ORDER BY started DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("  (keine Sessions)")
        return

    print(f"  {'Session ID':<30} {'Wallets':>7} {'Trades':>6} {'SELLs':>6} {'P&L EUR':>10}  {'Gestartet'}")
    print("  " + "─"*85)

    for r in rows:
        pnl_str = f"{r['total_pnl']:+.2f}" if r['total_pnl'] else "   n/a"
        started = r['started'][:16] if r['started'] else "?"
        print(
            f"  {r['session_id']:<30} "
            f"{r['wallets']:>7}  "
            f"{r['total_trades']:>5}x  "
            f"{r['sells']:>5}x  "
            f"{pnl_str:>9} EUR  "
            f"{started}"
        )

    print()
    print(f"  Gesamt: {len(rows)} Sessions")


def show_wallet_detail(wallet_prefix: str):
    """Zeigt alle Trades eines Wallets"""
    conn = connect()
    cursor = conn.cursor()

    # Wallet per Prefix suchen
    cursor.execute(
        "SELECT DISTINCT wallet FROM wallet_trades WHERE wallet LIKE ?",
        (wallet_prefix + "%",)
    )
    matches = [r['wallet'] for r in cursor.fetchall()]

    if not matches:
        print(f"  ❌ Kein Wallet gefunden für Prefix: '{wallet_prefix}'")
        conn.close()
        return

    if len(matches) > 1:
        print(f"  ⚠️  Mehrere Wallets gefunden – bitte längeren Prefix angeben:")
        for m in matches:
            print(f"    {m}")
        conn.close()
        return

    wallet = matches[0]

    # Stats
    cursor.execute("SELECT * FROM wallet_stats WHERE wallet = ?", (wallet,))
    stats = cursor.fetchone()

    # Trades
    cursor.execute("""
        SELECT * FROM wallet_trades
        WHERE wallet = ? AND side = 'SELL' AND pnl_eur IS NOT NULL
        ORDER BY timestamp DESC
    """, (wallet,))
    trades = cursor.fetchall()
    conn.close()

    print(f"  🔑 Wallet: {wallet}")
    if stats:
        conf = stats['confidence_score']
        bar  = "█" * int(conf * 20) + "░" * (20 - int(conf * 20))
        print(f"  Confidence:  {bar} {conf:.2f}")
        print(f"  Trades:      {stats['total_trades']} ({stats['winning_trades']}W / {stats['losing_trades']}L)")
        print(f"  Win Rate:    {stats['win_rate']*100:.1f}%")
        print(f"  Total P&L:   {stats['total_pnl_eur']:+.2f} EUR")
        print(f"  Avg P&L:     {stats['avg_pnl_eur']:+.2f} EUR")
        print(f"  Aktualisiert: {stats['last_updated'][:16]}")
    
    if not trades:
        print("\n  Keine abgeschlossenen Trades.")
        return

    print()
    print(f"  {'Session':<25} {'Token':<12} {'Entry':>12} {'Exit':>12} {'P&L EUR':>10} {'P&L%':>8}  {'Datum'}")
    print("  " + "─"*95)

    for t in trades:
        emoji  = "✅" if (t['pnl_eur'] or 0) >= 0 else "❌"
        pnl    = t['pnl_eur'] or 0
        pct    = t['pnl_percent'] or 0
        ts     = t['timestamp'][:16]
        token  = t['token'][:10]
        print(
            f"  {emoji} {t['session_id'][:23]:<23}  "
            f"{token:<12}  "
            f"{t.get('entry_price_eur', t['price_eur']):>12.8f}  "
            f"{t['price_eur']:>12.8f}  "
            f"{pnl:>+9.2f}  "
            f"{pct:>+7.1f}%  "
            f"{ts}"
        )


def print_help():
    print()
    print("="*60)
    print("📊 WALLET DATABASE VIEWER")
    print("="*60)
    print()
    print("Usage:")
    print("  python main.py show_db                     – Alle Wallets (sortiert nach Confidence)")
    print("  python main.py show_db pnl                 – Sortiert nach P&L")
    print("  python main.py show_db winrate             – Sortiert nach Win-Rate")
    print("  python main.py show_db trades              – Sortiert nach Trade-Anzahl")
    print("  python main.py show_db --min 5             – Nur Wallets mit min. 5 Trades")
    print("  python main.py show_db sessions            – Alle Sessions anzeigen")
    print("  python main.py show_db wallet <PREFIX>     – Detail-Ansicht eines Wallets")
    print()


def run(args: list):
    """Entry Point – wird von main.py aufgerufen"""

    try:
        conn = connect()
        conn.close()
    except Exception:
        print(f"\n❌ Datenbank nicht gefunden: {DB_PATH}")
        print("   Starte zuerst: python main.py wallet_analysis\n")
        return

    # Args parsen
    sort_by = "confidence"
    min_trades = 0
    mode = "stats"
    wallet_prefix = None

    i = 0
    while i < len(args):
        arg = args[i].lower()
        if arg in ("pnl", "winrate", "trades", "confidence"):
            sort_by = arg
        elif arg == "--min" and i + 1 < len(args):
            try:
                min_trades = int(args[i + 1])
                i += 1
            except ValueError:
                pass
        elif arg == "sessions":
            mode = "sessions"
        elif arg == "wallet" and i + 1 < len(args):
            mode = "wallet"
            wallet_prefix = args[i + 1]
            i += 1
        elif arg in ("-h", "--help", "help"):
            print_help()
            return
        i += 1

    print()

    if mode == "sessions":
        print("="*70)
        print("📋 SESSION ÜBERSICHT")
        print("="*70)
        show_sessions()

    elif mode == "wallet":
        print("="*70)
        print("🔍 WALLET DETAIL")
        print("="*70)
        show_wallet_detail(wallet_prefix)

    else:
        sort_labels = {
            "confidence": "Confidence Score",
            "pnl":        "Total P&L",
            "winrate":    "Win Rate",
            "trades":     "Trade Anzahl",
        }
        print("="*70)
        print(f"📊 WALLET DATENBANK  –  sortiert nach {sort_labels.get(sort_by, sort_by)}")
        print("="*70)
        show_wallet_stats(min_trades, sort_by)

    print()
