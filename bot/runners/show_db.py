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
        SELECT
            ws.*,
            ROUND(
                SUM(CASE WHEN wt.price_missing = 0 THEN wt.pnl_percent ELSE 0 END) /
                NULLIF(COUNT(CASE WHEN wt.price_missing = 0 AND wt.pnl_percent IS NOT NULL THEN 1 END), 0)
            , 1) as ev_pct
        FROM wallet_stats ws
        LEFT JOIN wallet_trades wt
            ON wt.wallet = ws.wallet
            AND wt.side = 'SELL'
            AND wt.pnl_percent IS NOT NULL
        WHERE ws.total_trades >= ?
        GROUP BY ws.wallet
        ORDER BY {order}
    """, (filter_min_trades,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("  (keine Einträge)")
        return

    from trading.wallet_tracker import STRATEGY_SL_TP_DEFAULTS

    # Spaltenbreiten
    C_IDX    = 3
    C_WALLET = 16
    C_TRADES = 5
    C_WIN    = 5
    C_AVG    = 10
    C_CONF   = 5
    C_LABEL  = 11  # "LOSS_MAKER" ist längstes Label
    C_SL     = 7
    C_TP     = 8
    C_DATE   = 16

    header = (
        f"  {'#':>{C_IDX}}  {'Wallet':<{C_WALLET}}"
        f"  {'Trades':>{C_TRADES}}  {'Win%':>{C_WIN}}"
        f"  {'EV %':>{C_AVG}}"
        f"  {'Conf':>{C_CONF}}  {'Strategy':<{C_LABEL}}  {'SL':>{C_SL}}  {'TP':>{C_TP}}  Updated"
    )
    divider = "  " + "─" * (C_IDX + C_WALLET + C_TRADES + C_WIN + C_AVG + C_CONF + C_LABEL + C_SL + C_TP + C_DATE + 22)
    print(header)
    print(divider)

    for i, r in enumerate(rows, 1):
        conf     = r['confidence_score']
        wr_str   = f"{r['win_rate']*100:.0f}%"
        ev_str   = f"{r['ev_pct']:+.1f}%" if r['ev_pct'] is not None else "n/a"
        updated  = r['last_updated'][:16].replace('T', ' ')
        label    = r['strategy_label'] if 'strategy_label' in r.keys() else 'UNKNOWN'
        # Dynamische SL/TP bevorzugen, Fallback auf Label-Defaults
        dyn_sl   = r['dynamic_sl'] if 'dynamic_sl' in r.keys() and r['dynamic_sl'] is not None else None
        dyn_tp   = r['dynamic_tp'] if 'dynamic_tp' in r.keys() and r['dynamic_tp'] is not None else None
        if dyn_sl is not None and dyn_tp is not None:
            sl, tp   = dyn_sl, dyn_tp
            sl_str   = f"{sl:.0f}%*"   # * = dynamisch
            tp_str   = f"+{tp:.0f}%*"
        elif label != 'UNKNOWN':
            sl, tp   = STRATEGY_SL_TP_DEFAULTS.get(label, STRATEGY_SL_TP_DEFAULTS['UNKNOWN'])
            sl_str   = f"{sl:.0f}%"
            tp_str   = f"+{tp:.0f}%"
        else:
            sl_str   = "--"
            tp_str   = "--"
        marker   = "+" if conf >= 0.7 else "~" if conf >= 0.5 else "-"

        print(
            f"  {i:>{C_IDX}}  {marker} {r['wallet'][:C_WALLET]:<{C_WALLET}}"
            f"  {r['total_trades']:>{C_TRADES}}x  {wr_str:>{C_WIN}}"
            f"  {ev_str:>{C_AVG}}"
            f"  {conf:>{C_CONF}.2f}  {label:<{C_LABEL}}  {sl_str:>{C_SL}}  {tp_str:>{C_TP}}  {updated}"
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
        from trading.wallet_tracker import STRATEGY_SL_TP_DEFAULTS
        conf  = stats['confidence_score']
        label = stats['strategy_label'] if 'strategy_label' in stats.keys() else 'UNKNOWN'
        dyn_sl = stats['dynamic_sl'] if 'dynamic_sl' in stats.keys() and stats['dynamic_sl'] is not None else None
        dyn_tp = stats['dynamic_tp'] if 'dynamic_tp' in stats.keys() and stats['dynamic_tp'] is not None else None
        if dyn_sl is not None and dyn_tp is not None:
            sl, tp = dyn_sl, dyn_tp
            sl_tp_source = "dynamisch*"
        else:
            sl, tp = STRATEGY_SL_TP_DEFAULTS.get(label, STRATEGY_SL_TP_DEFAULTS['UNKNOWN'])
            sl_tp_source = "label-default"
        # Inaktivitäts-Tags aus DB lesen
        tag_conn = sqlite3.connect(DB_PATH)
        tag_conn.row_factory = sqlite3.Row
        tag_cur = tag_conn.cursor()
        tag_cur.execute("SELECT tags FROM wallet_inactivity_tags WHERE wallet = ?", (wallet,))
        tag_row = tag_cur.fetchone()
        tag_conn.close()
        tags = tag_row['tags'] if tag_row else 0
        max_tags = 3
        timeout = "5 Min" if tags >= max_tags else "10 Min"

        print(f"  Confidence:  {conf:.2f}")
        if label != 'UNKNOWN':
            print(f"  Strategie:   {label}  →  SL {sl:.0f}% / TP +{tp:.0f}%  [{sl_tp_source}]")
        else:
            print(f"  Strategie:   {label}  (noch < 20 saubere Trades)")
        print(f"  Inaktivität: {'[' + 'X' * tags + '.' * (max_tags - tags) + ']'} {tags}/{max_tags} Tags  →  Timeout {timeout}")
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
