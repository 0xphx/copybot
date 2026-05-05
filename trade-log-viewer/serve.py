#!/usr/bin/env python3
"""
Local dashboard server for past Copybot trades.

Scans JSON files from the copybot data directory and renders charts on demand.
"""

from __future__ import annotations

import argparse
import subprocess
import urllib.parse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from viewer import DEFAULT_COPYBOT_DATA_DIR, collect_dashboard_rows, generate_chart, sanitize_token


BASE_DIR = Path(__file__).resolve().parent


def make_chart_filename(session_name: str, token: str, currency: str) -> str:
    stem = Path(session_name).stem
    return f"{stem}__{sanitize_token(token)}__{currency}.html"


def build_dashboard_html(source_dir: Path, display_currency: str) -> str:
    rows = collect_dashboard_rows(source_dir)
    session_count = len({row.session_name for row in rows})
    total_buy = sum(row.buy_count for row in rows)
    total_sell = sum(row.sell_count for row in rows)

    table_rows = []
    for row in rows:
        query = urllib.parse.urlencode(
            {
                "session": row.session_name,
                "token": row.token,
                "currency": display_currency,
            }
        )
        chart_href = f"/chart?{query}"
        table_rows.append(
            f"""
            <tr data-search="{escape((row.session_name + ' ' + row.token).lower())}">
              <td>{escape(row.session_name)}</td>
              <td class="token">{escape(row.token)}</td>
              <td>{row.buy_count}</td>
              <td>{row.sell_count}</td>
              <td class="pnl {'pos' if row.realized_pnl_eur >= 0 else 'neg'}">{row.realized_pnl_eur:+.2f} EUR</td>
              <td>{escape(row.first_trade_at.isoformat(sep=' ', timespec='minutes'))}</td>
              <td>{escape(row.last_trade_at.isoformat(sep=' ', timespec='minutes'))}</td>
              <td><a href="{chart_href}" target="_blank">Chart öffnen</a></td>
            </tr>
            """
        )

    if not table_rows:
        table_rows.append(
            """
            <tr>
              <td colspan="8">Keine passenden Session-Dateien gefunden.</td>
            </tr>
            """
        )

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trade Log Dashboard</title>
  <style>
    body {{
      margin: 0;
      background: #06101d;
      color: #e5e7eb;
      font-family: Arial, sans-serif;
    }}
    .wrap {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 18px;
    }}
    .meta {{
      color: #94a3b8;
      font-size: 14px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card {{
      background: linear-gradient(180deg, #0f172a, #09101d);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 14px;
      padding: 14px 16px;
    }}
    .card strong {{
      display: block;
      color: #93c5fd;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    input, select {{
      background: #0f172a;
      color: #e5e7eb;
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
    }}
    button, .button {{
      background: linear-gradient(180deg, #13233d, #0c172a);
      color: #e5e7eb;
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      font-size: 14px;
      text-decoration: none;
      display: inline-block;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      border-radius: 16px;
      background: #0a1424;
      border: 1px solid rgba(148, 163, 184, 0.18);
    }}
    th, td {{
      text-align: left;
      padding: 12px 14px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.1);
      font-size: 14px;
    }}
    th {{
      color: #93c5fd;
      background: #0d182b;
      position: sticky;
      top: 0;
    }}
    tr:hover {{
      background: rgba(96, 165, 250, 0.06);
    }}
    .token {{
      font-family: monospace;
      font-size: 13px;
    }}
    .pnl.pos {{ color: #34d399; }}
    .pnl.neg {{ color: #fb7185; }}
    a {{
      color: #93c5fd;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>Vergangene Trades</h1>
        <div class="meta">Quelle: {escape(str(source_dir))}</div>
      </div>
      <div class="meta">Charts werden beim Klick automatisch erzeugt und geöffnet.</div>
    </div>

    <div class="cards">
      <div class="card"><strong>Sessions</strong>{session_count}</div>
      <div class="card"><strong>Trade-Gruppen</strong>{len(rows)}</div>
      <div class="card"><strong>Buys</strong>{total_buy}</div>
      <div class="card"><strong>Sells</strong>{total_sell}</div>
      <div class="card"><strong>Chart-Währung</strong>{escape(display_currency)}</div>
    </div>

    <div class="toolbar">
      <input id="search" type="text" placeholder="Nach Session oder Token filtern">
      <select id="currency">
        <option value="EUR" {"selected" if display_currency == "EUR" else ""}>EUR</option>
        <option value="USD" {"selected" if display_currency == "USD" else ""}>USD</option>
      </select>
      <a class="button" id="reload" href="/?currency={escape(display_currency)}">Neu laden</a>
    </div>

    <table>
      <thead>
        <tr>
          <th>Session</th>
          <th>Token</th>
          <th>Buys</th>
          <th>Sells</th>
          <th>Realized PnL</th>
          <th>Erster Trade</th>
          <th>Letzter Trade</th>
          <th>Aktion</th>
        </tr>
      </thead>
      <tbody id="rows">
        {''.join(table_rows)}
      </tbody>
    </table>
  </div>
  <script>
    const search = document.getElementById('search');
    const rows = Array.from(document.querySelectorAll('#rows tr[data-search]'));
    const currency = document.getElementById('currency');
    const reload = document.getElementById('reload');

    search.addEventListener('input', () => {{
      const value = search.value.trim().toLowerCase();
      for (const row of rows) {{
        row.style.display = row.dataset.search.includes(value) ? '' : 'none';
      }}
    }});

    currency.addEventListener('change', () => {{
      const params = new URLSearchParams(window.location.search);
      params.set('currency', currency.value);
      window.location.search = params.toString();
    }});
  </script>
</body>
</html>
"""


def build_chart_error_html(session_name: str, token: str, currency: str, error_message: str) -> str:
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chart nicht verfügbar</title>
  <style>
    body {{
      margin: 0;
      background: #06101d;
      color: #e5e7eb;
      font-family: Arial, sans-serif;
    }}
    .wrap {{
      max-width: 980px;
      margin: 0 auto;
      padding: 28px;
    }}
    .card {{
      background: linear-gradient(180deg, #0f172a, #09101d);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 16px;
      padding: 18px 20px;
      margin-bottom: 14px;
    }}
    .meta {{
      color: #94a3b8;
      margin-bottom: 8px;
      font-size: 14px;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #07111f;
      border-radius: 12px;
      padding: 14px;
      border: 1px solid rgba(148, 163, 184, 0.12);
      color: #dbeafe;
    }}
    a {{
      color: #93c5fd;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Chart derzeit nicht verfügbar</h1>
      <div class="meta">Session: {escape(session_name)}</div>
      <div class="meta">Token: {escape(token)}</div>
      <div class="meta">Währung: {escape(currency)}</div>
      <p>Für diesen Trade konnte keine passende historische Candle-Serie geladen werden. Das passiert bei sehr illiquiden Pools oder wenn GeckoTerminal für den relevanten Zeitraum keine OHLCV-Historie hat.</p>
    </div>
    <div class="card">
      <strong>Fehlerdetails</strong>
      <pre>{escape(error_message)}</pre>
      <p><a href="/?currency={escape(currency)}">Zurück zum Dashboard</a></p>
    </div>
  </div>
</body>
</html>
"""


def make_handler(source_dir: Path, default_currency: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if parsed.path == "/":
                currency = params.get("currency", [default_currency])[0].upper()
                html = build_dashboard_html(source_dir, currency)
                self._send_html(html)
                return

            if parsed.path == "/chart":
                session_name = params.get("session", [""])[0]
                token = params.get("token", [""])[0]
                currency = params.get("currency", [default_currency])[0].upper()

                if not session_name or not token:
                    self.send_error(400, "Missing session or token")
                    return

                session_path = source_dir / session_name
                if not session_path.exists():
                    self.send_error(404, f"Session not found: {session_name}")
                    return

                output_path = BASE_DIR / "out" / make_chart_filename(session_name, token, currency)
                try:
                    generate_chart(BASE_DIR, session_path, token, currency, output=str(output_path))
                    html = output_path.read_text(encoding="utf-8")
                except Exception as exc:
                    html = build_chart_error_html(session_name, token, currency, str(exc))
                    self._send_html(html)
                    return

                self._send_html(html)
                return

            self.send_error(404, "Not found")

        def log_message(self, format, *args):
            return

        def _send_html(self, html: str):
            encoded = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Local dashboard for past Copybot trades.")
    parser.add_argument("--source-dir", default=str(DEFAULT_COPYBOT_DATA_DIR), help="Directory with paper_mainnet_*.json / paper_trading_*.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--display-currency", choices=["EUR", "USD"], default="EUR")
    parser.add_argument("--open", action="store_true", help="Open dashboard in browser")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.exists():
        raise SystemExit(f"Source dir not found: {source_dir}")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(source_dir, args.display_currency))
    url = f"http://{args.host}:{args.port}/?currency={args.display_currency}"
    print(f"[ok] Dashboard läuft auf {url}")

    if args.open:
        subprocess.run(["open", url], check=False)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[stop] Dashboard beendet")


if __name__ == "__main__":
    main()
