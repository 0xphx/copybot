"""
Show DB - Gibt die wallet_performance.db im Terminal aus
"""
import sqlite3
import sys
from datetime import datetime

DB_PATH_ANALYSIS = "data/wallet_performance.db"
DB_PATH_OBSERVER = "data/observer_performance.db"

# Wird in run() gesetzt
_active_db_path = DB_PATH_ANALYSIS


def connect():
    conn = sqlite3.connect(_active_db_path)
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
            ROUND(AVG(CASE WHEN wt.price_missing = 0 AND wt.pnl_eur > 0  THEN wt.pnl_percent END), 1) as avg_win_pct,
            ROUND(AVG(CASE WHEN wt.price_missing = 0 AND wt.pnl_eur <= 0 THEN wt.pnl_percent END), 1) as avg_loss_pct,
            MAX(CASE WHEN wt.price_missing = 0 AND wt.pnl_eur > 0        THEN wt.pnl_percent END) as max_win_pct,
            COUNT(CASE WHEN wt.price_missing = 0 AND wt.pnl_eur > 0      THEN 1 END)             as win_count
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
        print("  (keine Eintraege)")
        return

    # --- Werte vorberechnen (fuer dynamische Spaltenbreiten) ---
    rendered = []
    for r in rows:
        conf      = r['confidence_score']
        wr        = r['win_rate']
        avgw      = r['avg_win_pct']
        avgl      = r['avg_loss_pct']
        max_win   = r['max_win_pct'] if 'max_win_pct' in r.keys() else None
        win_count = r['win_count']   if 'win_count'   in r.keys() else 0
        outlier   = (
            avgw is not None and max_win is not None
            and win_count >= 3
            and max_win > avgw * 5
        )
        avgw_str = f"+{avgw:.0f}%*" if (avgw is not None and outlier) else (f"+{avgw:.0f}%" if avgw is not None else "n/a")
        avgl_str = f"{avgl:.0f}%"   if avgl is not None else "n/a"
        if avgw is not None and avgl is not None:
            ev     = wr * avgw + (1 - wr) * avgl
            ev_str = f"{ev:+.0f}%*" if outlier else f"{ev:+.0f}%"
        else:
            ev_str = "n/a"
        label   = r['strategy_label'] if 'strategy_label' in r.keys() else 'UNKNOWN'
        marker  = "+" if conf >= 0.7 else "~" if conf >= 0.5 else "-"
        updated = r['last_updated'][:16].replace('T', ' ')
        rendered.append({
            'wallet': r['wallet'], 'trades': r['total_trades'],
            'wr': f"{wr*100:.0f}%", 'conf': conf,
            'avgw_str': avgw_str, 'avgl_str': avgl_str, 'ev_str': ev_str,
            'label': label, 'marker': marker, 'updated': updated,
            'outlier': outlier,
        })

    # --- Dynamische Spaltenbreiten: max(Header, laengster Wert) + 1 Puffer ---
    # Wallet-Spalte schliesst marker (1 Zeichen) + Leerzeichen (1) ein -> +2
    C_IDX    = max(3,  max(len(str(i+1))          for i in range(len(rendered))))
    C_WALLET = max(18, max(len(r['wallet'][:44])   for r in rendered) + 2)  # +2 fuer "x "
    C_TRADES = max(5,  max(len(f"{r['trades']}x")  for r in rendered))
    C_WIN    = max(5,  max(len(r['wr'])             for r in rendered))
    C_AVGW   = max(6,  max(len(r['avgw_str'])       for r in rendered)) + 1
    C_AVGL   = max(7,  max(len(r['avgl_str'])       for r in rendered)) + 1
    C_EV     = max(4,  max(len(r['ev_str'])         for r in rendered)) + 1
    C_CONF   = 5
    C_LABEL  = max(5,  max(len(r['label'])          for r in rendered)) + 1
    C_DATE   = 16

    # Wallet-Spalte: marker (1) + Leerzeichen (1) + wallet-name
    # Damit Header-"Wallet" und Daten-Wallet buendig sind:
    wallet_col_w = C_WALLET  # gesamt fuer "x name"

    header = (
        f"  {'#':>{C_IDX}}  {'Wallet':<{wallet_col_w}}"
        f"  {'T':>{C_TRADES}}  {'WR%':>{C_WIN}}"
        f"  {'avgWin':>{C_AVGW}}  {'avgLoss':>{C_AVGL}}"
        f"  {'EV':>{C_EV}}"
        f"  {'Conf':>{C_CONF}}  {'Label':<{C_LABEL}}  Updated"
    )
    total_w = C_IDX + wallet_col_w + C_TRADES + C_WIN + C_AVGW + C_AVGL + C_EV + C_CONF + C_LABEL + C_DATE + 20
    print(header)
    print("  " + "-" * total_w)

    for i, r in enumerate(rendered, 1):
        # marker + Leerzeichen + wallet zusammen in wallet_col_w
        wallet_cell = f"{r['marker']} {r['wallet']}"
        print(
            f"  {i:>{C_IDX}}  {wallet_cell:<{wallet_col_w}}"
            f"  {r['trades']:>{C_TRADES}}x  {r['wr']:>{C_WIN}}"
            f"  {r['avgw_str']:>{C_AVGW}}  {r['avgl_str']:>{C_AVGL}}"
            f"  {r['ev_str']:>{C_EV}}"
            f"  {r['conf']:>{C_CONF}.2f}  {r['label']:<{C_LABEL}}  {r['updated']}"
        )

    print()
    print(f"  Gesamt: {len(rows)} Wallets")
    if filter_min_trades > 0:
        print(f"  Filter: min. {filter_min_trades} Trades")
    if any(
        r['max_win_pct'] is not None and r['win_count'] >= 3
        and r['max_win_pct'] > r['avg_win_pct'] * 5
        for r in rows if r['avg_win_pct'] is not None and r['max_win_pct'] is not None
    ):
        print(f"  * = Ausreisser: max Win > 5x avgWin, Wert durch Einzeltrade verzerrt")


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
    print("  " + ""*85)

    for r in rows:
        pnl_str = f"{r['total_pnl']:+.2f}" if r['total_pnl'] else "   n/a"
        started = r['started'][:16] if r['started'] else "?"
        tag = "[OBS] " if r['session_id'].startswith('observer_') else "      "
        print(
            f"  {tag}{r['session_id']:<30} "
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
        print(f"   Kein Wallet gefunden für Prefix: '{wallet_prefix}'")
        conn.close()
        return

    if len(matches) > 1:
        print(f"    Mehrere Wallets gefunden  bitte längeren Prefix angeben:")
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

    print(f"   Wallet: {wallet}")
    if stats:
        conf  = stats['confidence_score']
        label = stats['strategy_label'] if 'strategy_label' in stats.keys() else 'UNKNOWN'

        # Avg Win / Loss aus wallet_trades berechnen
        detail_conn = sqlite3.connect(_active_db_path)
        detail_conn.row_factory = sqlite3.Row
        detail_cur = detail_conn.cursor()
        detail_cur.execute("""
            SELECT
                ROUND(AVG(CASE WHEN pnl_eur > 0  THEN pnl_percent END), 1) as avg_win_pct,
                ROUND(AVG(CASE WHEN pnl_eur <= 0 THEN pnl_percent END), 1) as avg_loss_pct
            FROM wallet_trades
            WHERE wallet = ? AND side = 'SELL' AND price_missing = 0 AND pnl_percent IS NOT NULL
        """, (wallet,))
        avgs = detail_cur.fetchone()

        # Inaktivitaets-Tags aus DB lesen
        detail_cur.execute("SELECT tags FROM wallet_inactivity_tags WHERE wallet = ?", (wallet,))
        tag_row = detail_cur.fetchone()
        detail_conn.close()

        tags = tag_row['tags'] if tag_row else 0
        max_tags = 3
        timeout = "5 Min" if tags >= max_tags else "10 Min"

        avgw = avgs['avg_win_pct']  if avgs else None
        avgl = avgs['avg_loss_pct'] if avgs else None
        avg_win_str  = f"+{avgw:.0f}%" if avgw is not None else "n/a"
        avg_loss_str = f"{avgl:.0f}%"  if avgl is not None else "n/a"
        if avgw is not None and avgl is not None:
            wr_val   = stats['win_rate']
            ev_val   = wr_val * avgw + (1 - wr_val) * avgl
            ev_str   = f"{ev_val:+.1f}%"
        else:
            ev_str = "n/a"

        print(f"  Confidence:  {conf:.2f}")
        print(f"  Label:       {label}")
        print(f"  Avg Win:     {avg_win_str}")
        print(f"  Avg Loss:    {avg_loss_str}")
        print(f"  EV:          {ev_str}")
        print(f"  Inaktivitaet: {'[' + 'X' * tags + '.' * (max_tags - tags) + ']'} {tags}/{max_tags} Tags  ->  Timeout {timeout}")
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
    print("  " + ""*95)

    for t in trades:
        emoji  = "" if (t['pnl_eur'] or 0) >= 0 else ""
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
    print(" WALLET DATABASE VIEWER")
    print("="*60)
    print()
    print("Usage:")
    print("  python main.py show_db                      Analysis-DB (wallet_performance.db)")
    print("  python main.py show_db --observer           Observer-DB (observer_performance.db)")
    print("  python main.py show_db pnl                  Sortiert nach P&L")
    print("  python main.py show_db winrate              Sortiert nach Win-Rate")
    print("  python main.py show_db trades               Sortiert nach Trade-Anzahl")
    print("  python main.py show_db --min 5              Nur Wallets mit min. 5 Trades")
    print("  python main.py show_db sessions             Alle Sessions anzeigen")
    print("  python main.py show_db wallet <PREFIX>      Detail-Ansicht eines Wallets")
    print()


def run(args: list):
    """Entry Point - wird von main.py aufgerufen"""
    global _active_db_path

    # --observer Flag zuerst parsen (bestimmt welche DB)
    observer_mode = "--observer" in [a.lower() for a in args]
    _active_db_path = DB_PATH_OBSERVER if observer_mode else DB_PATH_ANALYSIS
    db_label = "OBSERVER" if observer_mode else "ANALYSIS"

    try:
        conn = connect()
        conn.close()
    except Exception:
        print(f"\n Datenbank nicht gefunden: {_active_db_path}")
        if observer_mode:
            print("   Starte zuerst: python main.py wallet_analysis  -> Modus 2 (Observer)\n")
        else:
            print("   Starte zuerst: python main.py wallet_analysis  -> Modus 1 (Analysis)\n")
        return

    # Restliche Args parsen
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
        print(f" SESSION UEBERSICHT  [{db_label}]  ({_active_db_path})")
        print("="*70)
        show_sessions()

    elif mode == "wallet":
        print("="*70)
        print(f" WALLET DETAIL  [{db_label}]")
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
        print(f" WALLET DATENBANK  [{db_label}]  sortiert nach {sort_labels.get(sort_by, sort_by)}")
        print(f" DB: {_active_db_path}")
        print("="*70)
        show_wallet_stats(min_trades, sort_by)

    print()
