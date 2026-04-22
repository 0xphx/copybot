"""
Logs Runner - Interaktive Session-Uebersicht
Aufruf: python main.py logs              (Observer-DB, Standard)
        python main.py logs --analysis   (Analysis-DB)
"""
import sqlite3
import sys

DB_PATH_OBSERVER = "data/observer_performance.db"
DB_PATH_ANALYSIS = "data/wallet_performance.db"

REASON_SHORT = {
    "WALLET_SOLD":                       "Wallet sold",
    "OBSERVER_STAGNATION":               "Stagnation",
    "OBSERVER_MAX_HOLD":                 "Max hold",
    "PRICE_UNAVAILABLE":                 "No price",
    "SESSION_ENDED":                     "Session end",
    "STOP_LOSS":                         "Stop loss",
    "TAKE_PROFIT":                       "Take profit",
    "INACTIVITY":                        "Inactivity",
    "EMERGENCY_EXIT_CONNECTION_LOST":    "Emergency",
    "MISSED_SELL_DETECTED_ON_RECONNECT": "Missed sell",
    "CRASH_RECOVERY":                    "Crash rec.",
}


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def duration_str(started, ended):
    if not started or not ended:
        return "?"
    try:
        from datetime import datetime
        s = started[:19].replace("T", " ")
        e = ended[:19].replace("T", " ")
        secs = max(0, int((datetime.strptime(e, "%Y-%m-%d %H:%M:%S")
                         - datetime.strptime(s, "%Y-%m-%d %H:%M:%S")).total_seconds()))
        h, m = secs // 3600, (secs % 3600) // 60
        if h > 0:
            return f"{h}h {m:02d}m"
        return f"{m}m"
    except Exception:
        return "?"


def load_sessions(db_path):
    try:
        conn = connect(db_path)
        cur  = conn.cursor()
        cur.execute("""
            SELECT
                session_id,
                COUNT(DISTINCT wallet)                                                        AS wallets,
                COUNT(CASE WHEN side='BUY'  THEN 1 END)                                      AS buys,
                COUNT(CASE WHEN side='SELL' THEN 1 END)                                      AS sells,
                COUNT(CASE WHEN side='SELL' AND pnl_eur > 0  AND price_missing=0 THEN 1 END) AS wins,
                COUNT(CASE WHEN side='SELL' AND pnl_eur <= 0 AND price_missing=0 THEN 1 END) AS losses,
                ROUND(SUM(CASE WHEN side='SELL' AND price_missing=0
                               THEN pnl_eur ELSE 0 END), 2)                                  AS total_pnl,
                MIN(timestamp) AS started,
                MAX(timestamp) AS ended
            FROM wallet_trades
            GROUP BY session_id
            ORDER BY started DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"\n  DB-Fehler: {e}")
        return []


def fmt_pnl(val):
    """Formatiert P&L mit + Vorzeichen und 2 Dezimalstellen."""
    if val is None:
        val = 0.0
    return f"{val:+.2f}"


def fmt_pct(val):
    """Formatiert Prozent mit + Vorzeichen und 1 Dezimalstelle."""
    if val is None:
        val = 0.0
    return f"{val:+.1f}%"


def fmt_price(val):
    """Formatiert einen Preis mit 8 Dezimalstellen."""
    if val is None:
        val = 0.0
    return f"{val:.8f}"


def show_session_detail(db_path, session_id):
    conn = connect(db_path)
    cur  = conn.cursor()

    # Kopfzeile
    cur.execute("""
        SELECT
            COUNT(CASE WHEN side='BUY'  THEN 1 END)                                      AS buys,
            COUNT(CASE WHEN side='SELL' THEN 1 END)                                      AS sells,
            COUNT(DISTINCT wallet)                                                        AS wallets,
            COUNT(CASE WHEN side='SELL' AND pnl_eur > 0  AND price_missing=0 THEN 1 END) AS wins,
            COUNT(CASE WHEN side='SELL' AND pnl_eur <= 0 AND price_missing=0 THEN 1 END) AS losses,
            COUNT(CASE WHEN price_missing=1 THEN 1 END)                                  AS missing,
            ROUND(SUM(CASE WHEN side='SELL' AND price_missing=0
                           THEN pnl_eur ELSE 0 END), 2)                                  AS total_pnl,
            MIN(timestamp) AS started,
            MAX(timestamp) AS ended
        FROM wallet_trades WHERE session_id = ?
    """, (session_id,))
    hdr = dict(cur.fetchone())

    # Alle SELLs mit Entry-Preis aus passendem BUY
    cur.execute("""
        SELECT
            s.wallet,
            s.token,
            s.price_eur      AS exit_price,
            s.pnl_eur,
            s.pnl_percent,
            s.price_missing,
            s.reason,
            s.timestamp      AS sell_time,
            (
                SELECT b.price_eur
                FROM wallet_trades b
                WHERE b.session_id = s.session_id
                  AND b.wallet     = s.wallet
                  AND b.token      = s.token
                  AND b.side       = 'BUY'
                  AND b.timestamp <= s.timestamp
                ORDER BY b.timestamp DESC
                LIMIT 1
            ) AS entry_price
        FROM wallet_trades s
        WHERE s.session_id = ? AND s.side = 'SELL'
        ORDER BY s.timestamp ASC
    """, (session_id,))
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    sells  = hdr['sells']  or 0
    wins   = hdr['wins']   or 0
    losses = hdr['losses'] or 0
    wr     = (wins / sells * 100) if sells > 0 else 0.0
    pnl    = hdr['total_pnl'] or 0.0
    dur    = duration_str(hdr['started'], hdr['ended'])

    # ── Kopf ────────────────────────────────────────────────────────────
    print()
    print("=" * 95)
    print(f"  SESSION: {session_id}")
    print("=" * 95)
    print(f"  Zeitraum:  {(hdr['started'] or '?')[:16].replace('T',' ')}  ->  {(hdr['ended'] or '?')[:16].replace('T',' ')}   ({dur})")
    print(f"  Wallets:   {hdr['wallets']}   BUYs: {hdr['buys']}   SELLs: {sells}")
    print(f"  Win Rate:  {wr:.1f}%  ({wins}W / {losses}L)")
    print(f"  P&L:       {fmt_pnl(pnl)} EUR")
    if hdr['missing']:
        print(f"  Hinweis:   {hdr['missing']} Trade(s) ohne Preis [!]")
    print()

    if not trades:
        print("  Keine abgeschlossenen Trades.")
        return

    # ── Spaltenbreiten fest definiert ────────────────────────────────────
    # Alle Spalten haben feste Breiten - Header und Daten passen exakt
    C_NR     =  4   # "  1"
    C_WALLET = 12   # Wallet-Prefix
    C_TOKEN  = 12   # Token-Prefix
    C_ENTRY  = 16   # "  0.00000437 EUR" -> 16 Zeichen
    C_EXIT   = 16   # gleich
    C_PNL    = 12   # "  +3847.70"
    C_PCT    =  9   # "  +18.4%"
    C_FLAG   =  5   # "[!]  " oder "     "
    C_REASON = 14   # Exit-Grund
    C_DATE   = 16   # "2026-04-11 08:33"

    # Header-Zeile (alle Spalten exakt gleich breit wie Daten)
    header = (
        f"  {'#':>{C_NR}}"
        f"  {'Wallet':<{C_WALLET}}"
        f"  {'Token':<{C_TOKEN}}"
        f"  {'Entry EUR':>{C_ENTRY}}"
        f"  {'Exit EUR':>{C_EXIT}}"
        f"  {'P&L EUR':>{C_PNL}}"
        f"  {'P&L%':>{C_PCT}}"
        f"  {'':>{C_FLAG}}"
        f"  {'Exit-Grund':<{C_REASON}}"
        f"  Datum"
    )
    sep = "  " + "-" * (len(header) - 2)
    print(header)
    print(sep)

    running = 0.0
    for i, t in enumerate(trades, 1):
        pnl_t   = t['pnl_eur']     if t['pnl_eur']     is not None else 0.0
        pct     = t['pnl_percent'] if t['pnl_percent']  is not None else 0.0
        entry   = t['entry_price'] if t['entry_price']  is not None else t['exit_price'] or 0.0
        exit_p  = t['exit_price']  if t['exit_price']   is not None else 0.0
        flag    = "[!] " if t['price_missing'] else "    "
        reason  = REASON_SHORT.get(t['reason'] or '', (t['reason'] or 'n/a')[:C_REASON])
        ts      = (t['sell_time'] or '')[:16].replace("T", " ")
        wallet  = (t['wallet'] or '')[:C_WALLET]
        token   = (t['token']  or '')[:C_TOKEN]
        running += pnl_t

        # Alle Werte als Strings vorformatieren
        entry_s = fmt_price(entry)
        exit_s  = fmt_price(exit_p)
        pnl_s   = fmt_pnl(pnl_t)
        pct_s   = fmt_pct(pct)

        print(
            f"  {i:>{C_NR}}"
            f"  {wallet:<{C_WALLET}}"
            f"  {token:<{C_TOKEN}}"
            f"  {entry_s:>{C_ENTRY}}"
            f"  {exit_s:>{C_EXIT}}"
            f"  {pnl_s:>{C_PNL}}"
            f"  {pct_s:>{C_PCT}}"
            f"  {flag:<{C_FLAG}}"
            f"  {reason:<{C_REASON}}"
            f"  {ts}"
        )

    print(sep)
    # Summenzeile: P&L-Spalte bündig mit Datenspalte
    running_s = fmt_pnl(running)
    print(
        f"  {'':>{C_NR}}"
        f"  {'':>{C_WALLET}}"
        f"  {'GESAMT':<{C_TOKEN}}"
        f"  {'':>{C_ENTRY}}"
        f"  {'':>{C_EXIT}}"
        f"  {running_s:>{C_PNL}}"
        f"  {'':>{C_PCT}}"
    )
    print()
    if any(t['price_missing'] for t in trades):
        print("  [!] = kein Preis abrufbar, Totalverlust angenommen")
    print()


def run(args=None):
    if args is None:
        args = sys.argv[2:]

    use_analysis = "--analysis" in [a.lower() for a in (args or [])]
    db_path  = DB_PATH_ANALYSIS if use_analysis else DB_PATH_OBSERVER
    db_label = "ANALYSIS" if use_analysis else "OBSERVER"

    try:
        conn = connect(db_path)
        conn.close()
    except Exception:
        print(f"\n  Datenbank nicht gefunden: {db_path}")
        print("  Starte zuerst eine Session mit: python main.py wallet_analysis\n")
        return

    while True:
        sessions = load_sessions(db_path)

        # ── Session-Liste ────────────────────────────────────────────────
        print()
        print("=" * 80)
        print(f"  SESSION LOGS  [{db_label}]")
        print("=" * 80)

        if not sessions:
            print("  Keine Sessions vorhanden.")
            print()
            return

        # Feste Spaltenbreiten fuer die Liste
        C_IDX  =  3
        C_DATE = 10
        C_DUR  =  8
        C_W    =  2
        C_BUYS =  4
        C_SELL =  5
        C_WR   =  5
        C_EPNL = 12

        hdr = (
            f"  {'Nr':>{C_IDX}}  {'Datum':<{C_DATE}}  {'Dauer':>{C_DUR}}"
            f"  {'W':>{C_W}}  {'BUYs':>{C_BUYS}}  {'SELLs':>{C_SELL}}"
            f"  {'WR':>{C_WR}}  {'P&L EUR':>{C_EPNL}}  Session-ID"
        )
        print(hdr)
        print("  " + "-" * (len(hdr) - 2 + 36))   # +36 fuer Session-ID

        for idx, s in enumerate(sessions, 1):
            sells = s['sells'] or 0
            wins  = s['wins']  or 0
            wr    = (wins / sells * 100) if sells > 0 else 0.0
            pnl   = s['total_pnl'] or 0.0
            dur   = duration_str(s['started'], s['ended'])
            date  = (s['started'] or '?')[:10]
            sid   = s['session_id']
            pnl_s = fmt_pnl(pnl)

            print(
                f"  {idx:>{C_IDX}}  {date:<{C_DATE}}  {dur:>{C_DUR}}"
                f"  {s['wallets']:>{C_W}}  {s['buys']:>{C_BUYS}}  {sells:>{C_SELL}}"
                f"  {wr:>{C_WR-1}.0f}%  {pnl_s:>{C_EPNL}} EUR  {sid}"
            )

        print()
        print("  Eingabe: Nummer -> Session-Detail   |   q -> Beenden")
        print()

        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw.lower() in ("q", "quit", "exit", ""):
            break

        try:
            nr = int(raw)
        except ValueError:
            print(f"\n  Ungueltige Eingabe: '{raw}'  (Zahl oder 'q' eingeben)\n")
            continue

        if nr < 1 or nr > len(sessions):
            print(f"\n  Zahl muss zwischen 1 und {len(sessions)} liegen.\n")
            continue

        show_session_detail(db_path, sessions[nr - 1]['session_id'])

        try:
            input("  [ENTER] zurueck zur Liste   |   Ctrl+C zum Beenden")
        except (EOFError, KeyboardInterrupt):
            print()
            break

    print()
