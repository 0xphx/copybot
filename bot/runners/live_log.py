"""
Live Log Runner - Stunden-Zusammenfassung der aktuellen Session
Aufruf: python main.py live_log

Zwei Ausgabe-Modi:
  [1] Terminal  - Zusammenfassung jede volle Stunde im Terminal
  [2] API       - HTTP-Server auf Port 8080, JSON-Output fuer externe Tools

API Endpoints:
  GET /status       - Aktuelle Session-Zusammenfassung
  GET /trades       - Alle Trades der aktuellen Session
  GET /hourly       - P&L pro Stunde
  GET /positions    - Aktuell offene Positionen (aus DB)
"""

import sqlite3
import json
import time
import sys
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

DB_OBSERVER = "data/observer_performance.db"
DB_ANALYSIS = "data/wallet_performance.db"


# ──────────────────────────────────────────────────────────────────────────────
# Daten aus DB lesen
# ──────────────────────────────────────────────────────────────────────────────

def get_latest_session(db_path: str) -> str | None:
    """Gibt die Session-ID der aktuellsten Session zurueck."""
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()
        cur.execute("SELECT session_id FROM wallet_trades ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def get_session_summary(db_path: str, session_id: str) -> dict:
    """Laedt vollstaendige Zusammenfassung einer Session."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()

        # Gesamt-Stats
        cur.execute("""
            SELECT
                COUNT(CASE WHEN side='BUY'  THEN 1 END)                                        AS buys,
                COUNT(CASE WHEN side='SELL' THEN 1 END)                                        AS sells,
                COUNT(DISTINCT wallet)                                                          AS wallets,
                COUNT(CASE WHEN side='SELL' AND pnl_eur > 0  AND price_missing=0 THEN 1 END)   AS wins,
                COUNT(CASE WHEN side='SELL' AND pnl_eur <= 0 AND price_missing=0 THEN 1 END)   AS losses,
                COUNT(CASE WHEN price_missing=1 THEN 1 END)                                    AS missing,
                ROUND(SUM(CASE WHEN side='SELL' AND price_missing=0 THEN pnl_eur ELSE 0 END),2) AS total_pnl,
                MIN(timestamp) AS started,
                MAX(timestamp) AS last_trade
            FROM wallet_trades WHERE session_id = ?
        """, (session_id,))
        stats = dict(cur.fetchone())

        # P&L pro Stunde
        cur.execute("""
            SELECT
                strftime('%Y-%m-%d %H:00', timestamp) AS hour,
                COUNT(CASE WHEN side='SELL' THEN 1 END) AS sells,
                COUNT(CASE WHEN side='SELL' AND pnl_eur > 0 AND price_missing=0 THEN 1 END) AS wins,
                ROUND(SUM(CASE WHEN side='SELL' AND price_missing=0 THEN pnl_eur ELSE 0 END),2) AS pnl
            FROM wallet_trades
            WHERE session_id = ?
            GROUP BY hour
            ORDER BY hour ASC
        """, (session_id,))
        hourly = [dict(r) for r in cur.fetchall()]

        # Letzte 10 Trades
        cur.execute("""
            SELECT wallet, token, side, price_eur, pnl_eur, pnl_percent, reason, timestamp
            FROM wallet_trades
            WHERE session_id = ? AND side = 'SELL'
            ORDER BY timestamp DESC
            LIMIT 10
        """, (session_id,))
        recent = [dict(r) for r in cur.fetchall()]

        # Top Wallets nach P&L
        cur.execute("""
            SELECT
                wallet,
                COUNT(CASE WHEN side='SELL' THEN 1 END) AS trades,
                COUNT(CASE WHEN side='SELL' AND pnl_eur > 0 AND price_missing=0 THEN 1 END) AS wins,
                ROUND(SUM(CASE WHEN side='SELL' AND price_missing=0 THEN pnl_eur ELSE 0 END),2) AS pnl
            FROM wallet_trades
            WHERE session_id = ?
            GROUP BY wallet
            ORDER BY pnl DESC
            LIMIT 5
        """, (session_id,))
        top_wallets = [dict(r) for r in cur.fetchall()]

        conn.close()

        # Laufzeit berechnen
        runtime_str = "?"
        if stats.get("started"):
            try:
                started = datetime.fromisoformat(stats["started"].replace("T", " ")[:19])
                delta   = datetime.now() - started
                h, m    = int(delta.total_seconds() // 3600), int((delta.total_seconds() % 3600) // 60)
                runtime_str = f"{h}h {m:02d}m"
            except Exception:
                pass

        sells = stats["sells"] or 0
        wins  = stats["wins"]  or 0
        wr    = (wins / sells * 100) if sells > 0 else 0.0

        return {
            "session_id":   session_id,
            "timestamp":    datetime.now().isoformat(),
            "runtime":      runtime_str,
            "started":      stats.get("started", "?"),
            "last_trade":   stats.get("last_trade", "?"),
            "wallets":      stats["wallets"],
            "buys":         stats["buys"],
            "sells":        sells,
            "wins":         wins,
            "losses":       stats["losses"],
            "win_rate":     round(wr, 1),
            "total_pnl":    stats["total_pnl"] or 0.0,
            "price_missing":stats["missing"],
            "hourly":       hourly,
            "recent_trades":recent,
            "top_wallets":  top_wallets,
        }
    except Exception as e:
        return {"error": str(e)}


def get_last_hour_summary(db_path: str, session_id: str) -> dict:
    """Zusammenfassung der letzten 60 Minuten."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()

        since = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        cur.execute("""
            SELECT
                COUNT(CASE WHEN side='BUY'  THEN 1 END) AS buys,
                COUNT(CASE WHEN side='SELL' THEN 1 END) AS sells,
                COUNT(CASE WHEN side='SELL' AND pnl_eur > 0  AND price_missing=0 THEN 1 END) AS wins,
                COUNT(CASE WHEN side='SELL' AND pnl_eur <= 0 AND price_missing=0 THEN 1 END) AS losses,
                ROUND(SUM(CASE WHEN side='SELL' AND price_missing=0 THEN pnl_eur ELSE 0 END),2) AS pnl,
                COUNT(DISTINCT wallet) AS wallets
            FROM wallet_trades
            WHERE session_id = ? AND timestamp >= ?
        """, (session_id, since))
        row = dict(cur.fetchone())
        conn.close()

        sells = row["sells"] or 0
        wins  = row["wins"]  or 0
        wr    = (wins / sells * 100) if sells > 0 else 0.0

        return {
            "period":   "last_60min",
            "since":    since,
            "buys":     row["buys"],
            "sells":    sells,
            "wins":     wins,
            "losses":   row["losses"],
            "win_rate": round(wr, 1),
            "pnl":      row["pnl"] or 0.0,
            "wallets":  row["wallets"],
        }
    except Exception as e:
        return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# Terminal Ausgabe
# ──────────────────────────────────────────────────────────────────────────────

def print_hourly_summary(db_path: str, session_id: str):
    """Druckt eine formatierte Stunden-Zusammenfassung ins Terminal."""
    now     = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = get_session_summary(db_path, session_id)
    hourly  = get_last_hour_summary(db_path, session_id)

    print()
    print("=" * 65)
    print(f"  LIVE LOG  |  {now}  |  Laufzeit: {summary.get('runtime','?')}")
    print("=" * 65)

    # Letzte Stunde
    pnl_h   = hourly["pnl"]
    sign_h  = "+" if pnl_h >= 0 else ""
    print(f"  LETZTE STUNDE:")
    print(f"    Trades:   {hourly['buys']} BUYs  |  {hourly['sells']} SELLs")
    print(f"    Win Rate: {hourly['win_rate']:.1f}%  ({hourly['wins']}W / {hourly['losses']}L)")
    print(f"    P&L:      {sign_h}{pnl_h:.2f} EUR")
    print()

    # Session gesamt
    pnl_t   = summary["total_pnl"]
    sign_t  = "+" if pnl_t >= 0 else ""
    print(f"  SESSION GESAMT  ({summary.get('started','?')[:16]}):")
    print(f"    Trades:   {summary['buys']} BUYs  |  {summary['sells']} SELLs")
    print(f"    Win Rate: {summary['win_rate']:.1f}%  ({summary['wins']}W / {summary['losses']}L)")
    print(f"    P&L:      {sign_t}{pnl_t:.2f} EUR")
    print(f"    Wallets:  {summary['wallets']} aktiv")
    print()

    # Top Wallets
    if summary.get("top_wallets"):
        print(f"  TOP WALLETS:")
        for w in summary["top_wallets"]:
            sign = "+" if w["pnl"] >= 0 else ""
            wr   = (w["wins"] / w["trades"] * 100) if w["trades"] > 0 else 0
            print(f"    {w['wallet'][:12]}...  {sign}{w['pnl']:.2f} EUR  "
                  f"({w['trades']}x, {wr:.0f}% WR)")
    print()

    # Letzte 3 Trades
    recent = summary.get("recent_trades", [])[:3]
    if recent:
        print(f"  LETZTE TRADES:")
        for t in recent:
            pnl  = t.get("pnl_eur") or 0
            sign = "+" if pnl >= 0 else ""
            ts   = (t.get("timestamp") or "")[:16].replace("T", " ")
            print(f"    {t['wallet'][:8]}...  {t['token'][:8]}...  "
                  f"{sign}{pnl:.2f} EUR  {ts}")
    print("=" * 65)


def terminal_mode(db_path: str):
    """Gibt jede volle Stunde eine Zusammenfassung aus."""
    print()
    print("[LiveLog] Terminal-Modus gestartet")
    print("[LiveLog] Zusammenfassung jede volle Stunde + sofort beim Start")
    print("[LiveLog] Ctrl+C zum Beenden")
    print()

    session_id = get_latest_session(db_path)
    if not session_id:
        print("[LiveLog] Keine aktive Session gefunden.")
        return

    print(f"[LiveLog] Aktive Session: {session_id}")

    # Sofort beim Start ausgeben
    print_hourly_summary(db_path, session_id)

    while True:
        try:
            now     = datetime.now()
            # Naechste volle Stunde berechnen
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            wait      = (next_hour - now).total_seconds()
            print(f"[LiveLog] Naechste Zusammenfassung um {next_hour.strftime('%H:%M')} "
                  f"(in {int(wait//60)}m {int(wait%60)}s)")
            time.sleep(wait)

            # Session neu laden (koennte sich geaendert haben)
            session_id = get_latest_session(db_path) or session_id
            print_hourly_summary(db_path, session_id)

        except KeyboardInterrupt:
            print()
            print("[LiveLog] Beendet.")
            break


# ──────────────────────────────────────────────────────────────────────────────
# API Server
# ──────────────────────────────────────────────────────────────────────────────

_api_db_path   = DB_OBSERVER
_api_session   = None


class LiveLogHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # HTTP-Logs unterdruecken

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")  # CORS fuer deinen Freund
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global _api_session
        session_id = _api_session or get_latest_session(_api_db_path)

        if self.path == "/status" or self.path == "/":
            if not session_id:
                self.send_json({"error": "Keine aktive Session"}, 404)
                return
            self.send_json(get_session_summary(_api_db_path, session_id))

        elif self.path == "/hourly":
            if not session_id:
                self.send_json({"error": "Keine aktive Session"}, 404)
                return
            self.send_json(get_last_hour_summary(_api_db_path, session_id))

        elif self.path == "/trades":
            if not session_id:
                self.send_json({"error": "Keine aktive Session"}, 404)
                return
            try:
                conn = sqlite3.connect(_api_db_path)
                conn.row_factory = sqlite3.Row
                cur  = conn.cursor()
                cur.execute("""
                    SELECT * FROM wallet_trades
                    WHERE session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 100
                """, (session_id,))
                trades = [dict(r) for r in cur.fetchall()]
                conn.close()
                self.send_json({"session_id": session_id, "trades": trades})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/sessions":
            try:
                conn = sqlite3.connect(_api_db_path)
                conn.row_factory = sqlite3.Row
                cur  = conn.cursor()
                cur.execute("""
                    SELECT session_id,
                           COUNT(*) as trades,
                           MIN(timestamp) as started,
                           MAX(timestamp) as ended
                    FROM wallet_trades
                    GROUP BY session_id
                    ORDER BY started DESC
                    LIMIT 20
                """)
                sessions = [dict(r) for r in cur.fetchall()]
                conn.close()
                self.send_json({"sessions": sessions})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        else:
            self.send_json({"error": f"Unbekannter Endpoint: {self.path}",
                           "endpoints": ["/status", "/hourly", "/trades", "/sessions"]}, 404)


def api_mode(db_path: str, port: int = 8080):
    """Startet HTTP API Server."""
    global _api_db_path, _api_session
    _api_db_path = db_path
    _api_session = get_latest_session(db_path)

    server = HTTPServer(("0.0.0.0", port), LiveLogHandler)
    print()
    print(f"[LiveLog] API-Server gestartet auf Port {port}")
    print(f"[LiveLog] Aktive Session: {_api_session or 'keine'}")
    print()
    print(f"  Endpoints:")
    print(f"    http://localhost:{port}/status    <- Gesamt-Zusammenfassung")
    print(f"    http://localhost:{port}/hourly    <- Letzte 60 Minuten")
    print(f"    http://localhost:{port}/trades    <- Letzte 100 Trades")
    print(f"    http://localhost:{port}/sessions  <- Alle Sessions")
    print()
    print(f"  Fuer deinen Freund (von aussen erreichbar via Tailscale):")
    print(f"    http://100.93.6.111:{port}/status")
    print()
    print(f"[LiveLog] Ctrl+C zum Beenden")
    print()

    # Session alle 60s aktualisieren
    def refresh_session():
        global _api_session
        while True:
            time.sleep(60)
            _api_session = get_latest_session(_api_db_path)

    t = threading.Thread(target=refresh_session, daemon=True)
    t.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("[LiveLog] API-Server beendet.")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def run(args=None):
    if args is None:
        args = sys.argv[2:]

    use_analysis = "--analysis" in (args or [])
    db_path = DB_ANALYSIS if use_analysis else DB_OBSERVER
    port    = 8080
    for a in (args or []):
        if a.startswith("--port="):
            try:
                port = int(a.split("=")[1])
            except ValueError:
                pass

    print()
    print("=" * 50)
    print("  COPYBOT LIVE LOG")
    print("=" * 50)
    print()
    print("  Modus waehlen:")
    print("   [1]  Terminal  - Zusammenfassung jede volle Stunde")
    print("   [2]  API       - HTTP-Server fuer externe Tools")
    print()

    try:
        choice = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice == "1":
        terminal_mode(db_path)
    elif choice == "2":
        api_mode(db_path, port)
    else:
        print("  Ungueltige Eingabe.")
