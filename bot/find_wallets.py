"""
find_wallets.py - Findet profitable Solana-Wallets via GMGN.AI Smart Money API
und schreibt sie in axiom_wallets.json.

Normaler Aufruf (Claude-Extension aktiv + gmgn.ai offen):
  python find_wallets.py              # Vorschau
  python find_wallets.py --apply      # Neue Wallets hinzufuegen (bestehende bleiben!)

Optionen:
  --period 30d        Zeitraum: 1d / 7d / 30d (default: 7d)
  --tag fresh_wallet  Tag: smart_money / fresh_wallet / kol (default: smart_money)

Hinweis:
  Bereits vorhandene Wallets werden aus der Suche AUSGESCHLOSSEN.
  Es werden immer nur neue Wallets hinzugefuegt, nie bestehende ersetzt.

Wie es funktioniert:
  1. Python startet lokalen Server auf Port 9876
  2. Claude-Extension fuehrt Fetch im GMGN-Tab aus (kein CORS, kein Cloudflare)
  3. Daten kommen an Python -> Filter -> Ausgabe/Schreiben

  Kein Chrome/Extension? Dann erscheint ein JS-Snippet zum manuellen Ausfuehren
  in der Browser-Konsole auf gmgn.ai.

Filter (hier anpassbar):
  MIN_WIN_RATE      Mindest-Win-Rate (0.0 - 1.0)
  MIN_TRADES        Mindestanzahl abgeschlossener Trades im Zeitraum
  MIN_REALIZED_PNL  Mindest-Realized-PnL in USD (0 = kein Filter)
  MAX_AVG_HOLD_MIN  Max. durchschnittliche Haltedauer in Minuten (0 = deaktiviert)
  MIN_AVG_HOLD_MIN  Min. durchschnittliche Haltedauer in Minuten (0 = deaktiviert)
  DAYS_ACTIVE       Nur Wallets die in den letzten X Tagen aktiv waren
  MAX_WALLETS       Max. Wallets die hinzugefuegt werden
"""

import json
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone, timedelta

# -----------------------------------------------------------------------
# FILTER-EINSTELLUNGEN
# -----------------------------------------------------------------------
MIN_WIN_RATE      = 0.55    # Mindestens 55% Win-Rate
MIN_TRADES        = 20      # Mindestens 20 Trades im Zeitraum
MIN_REALIZED_PNL  = 500     # Mindestens +500 USD Realized PnL
MAX_AVG_HOLD_MIN  = 120     # Max 2h Haltedauer (0 = deaktiviert)
MIN_AVG_HOLD_MIN  = 2       # Min 2 Min Haltedauer (0 = deaktiviert)
DAYS_ACTIVE       = 3       # In den letzten 3 Tagen aktiv
MAX_WALLETS       = 20      # Max. neue Wallets

# GMGN Einstellungen
PERIOD            = "7d"
TAG               = "smart_money"
LIMIT             = 100
BRIDGE_PORT       = 9876
BRIDGE_TIMEOUT    = 60
# -----------------------------------------------------------------------

SCRIPT_DIR   = Path(__file__).parent
WALLETS_FILE = SCRIPT_DIR / "data" / "axiom_wallets.json"

_received_data = None
_server_error  = None


# -----------------------------------------------------------------------
# LOKALER EMPFAENGER-SERVER
# Nimmt POST /receive mit JSON-Body entgegen (vom Browser geschickt)
# -----------------------------------------------------------------------

class ReceiverHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global _received_data, _server_error
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')
        if self.path == "/receive":
            try:
                _received_data = json.loads(body)
            except Exception as e:
                _server_error = f"JSON-Fehler: {e}"
        elif self.path == "/error":
            try:
                _server_error = json.loads(body).get("error", "Unbekannt")
            except Exception:
                _server_error = "Unbekannter Fehler"

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


def _start_receiver(port: int):
    for p in [port, port + 1, port + 2]:
        try:
            srv = HTTPServer(("127.0.0.1", p), ReceiverHandler)
            t   = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            return srv, p
        except OSError:
            continue
    raise RuntimeError("Kein freier Port gefunden")


# -----------------------------------------------------------------------
# METHODE 1: Direkter Python-Request (klappt wenn kein Cloudflare)
# -----------------------------------------------------------------------

def _try_direct_fetch(period: str, tag: str, limit: int):
    import urllib.request, urllib.error
    period_map = {"1d": "pnl_1d", "7d": "pnl_7d", "30d": "pnl_30d"}
    orderby    = period_map.get(period, "pnl_7d")
    url        = (f"https://gmgn.ai/defi/quotation/v1/rank/sol/wallets/{period}"
                  f"?orderby={orderby}&direction=desc&period={period}"
                  f"&tag={tag}&wallet_tag={tag}&limit={limit}")
    headers = {
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "de-DE,de;q=0.9",
        "Referer":         "https://gmgn.ai/sol/wallets/smart_money",
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"),
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code") == 0:
            rows = data.get("data", {}).get("rank", [])
            if rows:
                print(f"[GMGN]  Direkter Zugriff OK: {len(rows)} Wallets.")
                return rows
    except Exception:
        pass
    return None


# -----------------------------------------------------------------------
# METHODE 2: Warten auf Browser-Inject
# Claude-Extension oder User fuehrt JS im GMGN-Tab aus
# -----------------------------------------------------------------------

def _fetch_via_browser(period: str, tag: str, limit: int) -> list:
    """
    Startet lokalen Server, zeigt JS-Snippet an.
    Wenn Claude-Extension aktiv: Sie fuehrt das Snippet automatisch aus.
    Sonst: User kopiert es in Browser-Konsole auf gmgn.ai.
    """
    global _received_data, _server_error
    _received_data = None
    _server_error  = None

    server, port = _start_receiver(BRIDGE_PORT)

    period_map = {"1d": "pnl_1d", "7d": "pnl_7d", "30d": "pnl_30d"}
    orderby    = period_map.get(period, "pnl_7d")
    api_url    = (f"https://gmgn.ai/defi/quotation/v1/rank/sol/wallets/{period}"
                  f"?orderby={orderby}&direction=desc&period={period}"
                  f"&tag={tag}&wallet_tag={tag}&limit={limit}")

    # JS-Snippet das der Browser im GMGN-Tab ausfuehren soll
    js = (
        f"(async()=>{{const r=await fetch('{api_url}',{{headers:{{'Accept':'application/json',"
        f"'Referer':'https://gmgn.ai/sol/wallets/smart_money'}},credentials:'include'}});"
        f"const d=await r.json();window._gmgn_result=d;"
        f"await fetch('http://127.0.0.1:{port}/receive',{{method:'POST',"
        f"headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});"
        f"return (d?.data?.rank||[]).length+' Wallets gesendet';}})();"
    )

    print()
    print("=" * 70)
    print(" GMGN Browser-Inject")
    print("=" * 70)
    print(f" Server wartet auf Port {port} (max {BRIDGE_TIMEOUT}s)...")
    print()
    print(" [Claude-Extension]: Fuehrt automatisch aus.")
    print()
    print(" [Manuell]: Oeffne gmgn.ai in Chrome -> F12 -> Console:")
    print()
    # Lesbares Snippet fuer manuelle Ausfuehrung
    print(f"fetch('{api_url[:70]}...',")
    print(f"  {{headers:{{'Accept':'application/json'}},credentials:'include'}})")
    print(f".then(r=>r.json())")
    print(f".then(d=>fetch('http://127.0.0.1:{port}/receive',{{method:'POST',")
    print(f"  headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}}))")
    print()
    print("=" * 70)

    # Warten auf Daten
    deadline = time.time() + BRIDGE_TIMEOUT
    while time.time() < deadline:
        if _received_data is not None:
            server.shutdown()
            rows = _received_data.get("data", {}).get("rank", [])
            print(f"\n[GMGN]  {len(rows)} Wallets empfangen.")
            return rows
        if _server_error is not None:
            server.shutdown()
            print(f"\n[Fehler] {_server_error}")
            sys.exit(1)
        time.sleep(0.3)

    server.shutdown()
    print(f"\n[Fehler] Timeout nach {BRIDGE_TIMEOUT}s.")
    sys.exit(1)


def _fetch_gmgn(period: str, tag: str, limit: int) -> list:
    print(f"[GMGN] Lade Wallets: tag={tag}, period={period}, limit={limit}...")

    # Zuerst direkten Zugriff probieren
    rows = _try_direct_fetch(period, tag, limit)
    if rows:
        return rows

    # Cloudflare blockiert -> Browser-Methode
    print("[GMGN] Cloudflare aktiv. Wechsle zu Browser-Methode...")
    return _fetch_via_browser(period, tag, limit)


# -----------------------------------------------------------------------
# FILTER & NORMALISIERUNG
# -----------------------------------------------------------------------

def _normalize(row: dict, period: str) -> dict:
    win_rate     = float(row.get(f"winrate_{period}", row.get("winrate_7d", 0.0)) or 0.0)
    trades       = int(row.get(f"buy_{period}", row.get("buy_7d", 0)) or 0)
    realized     = float(row.get(f"realized_profit_{period}",
                                  row.get("realized_profit_7d", 0.0)) or 0.0)
    avg_hold     = float(row.get(f"avg_holding_period_{period}",
                                  row.get("avg_holding_period_7d", 0.0)) or 0.0)
    avg_hold_min = avg_hold / 60.0 if avg_hold else 0.0
    last_ts      = int(row.get("last_active", 0) or 0)
    last_dt      = (datetime.fromtimestamp(last_ts, tz=timezone.utc) if last_ts else None)
    return {
        "wallet":       row.get("wallet_address", row.get("address", "")),
        "win_rate":     win_rate,
        "trades":       trades,
        "realized_usd": realized,
        "avg_hold_min": avg_hold_min,
        "last_active":  last_dt,
        "nickname":     row.get("nickname") or row.get("twitter_name") or "",
        "tags":         row.get("tags") or [],
    }


def _filter_wallets(rows: list, period: str, existing_wallets: set = None) -> list:
    cutoff  = datetime.now(timezone.utc) - timedelta(days=DAYS_ACTIVE)
    existing = existing_wallets or set()
    results = []
    skipped = {"no_addr": 0, "win_rate": 0, "trades": 0, "pnl": 0,
               "hold_max": 0, "hold_min": 0, "inactive": 0, "existing": 0}

    for row in rows:
        n = _normalize(row, period)
        if not n["wallet"] or len(n["wallet"]) < 30:
            skipped["no_addr"] += 1; continue
        if n["wallet"] in existing:
            skipped["existing"] += 1; continue
        if n["win_rate"] < MIN_WIN_RATE:
            skipped["win_rate"] += 1; continue
        if n["trades"] < MIN_TRADES:
            skipped["trades"] += 1; continue
        if MIN_REALIZED_PNL > 0 and n["realized_usd"] < MIN_REALIZED_PNL:
            skipped["pnl"] += 1; continue
        if MAX_AVG_HOLD_MIN > 0 and n["avg_hold_min"] > MAX_AVG_HOLD_MIN:
            skipped["hold_max"] += 1; continue
        if MIN_AVG_HOLD_MIN > 0 and n["avg_hold_min"] < MIN_AVG_HOLD_MIN:
            skipped["hold_min"] += 1; continue
        if n["last_active"] and n["last_active"] < cutoff:
            skipped["inactive"] += 1; continue
        results.append(n)

    results.sort(key=lambda x: (-x["win_rate"], -x["realized_usd"]))

    print(f"[Filter] Aussortiert:  "
          f"Vorhanden={skipped['existing']}  "
          f"WR<{MIN_WIN_RATE*100:.0f}%={skipped['win_rate']}  "
          f"T<{MIN_TRADES}={skipped['trades']}  "
          f"PnL<${MIN_REALIZED_PNL}={skipped['pnl']}  "
          f"Hold>{MAX_AVG_HOLD_MIN}m={skipped['hold_max']}  "
          f"Hold<{MIN_AVG_HOLD_MIN}m={skipped['hold_min']}  "
          f"Inaktiv={skipped['inactive']}")

    return results[:MAX_WALLETS]


# -----------------------------------------------------------------------
# AUSGABE & SCHREIBEN
# -----------------------------------------------------------------------

def _load_current_wallets() -> list:
    if not WALLETS_FILE.exists():
        return []
    return json.loads(WALLETS_FILE.read_text(encoding="utf-8"))


def _print_results(filtered: list, current_wallets: list, period: str, tag: str) -> int:
    current_addrs = {w["wallet"] for w in current_wallets}
    new_count = 0

    print()
    print("=" * 80)
    print(f" GEFUNDENE WALLETS ({len(filtered)}) - {tag} | {period} | Filter:")
    print(f"   WR>={MIN_WIN_RATE*100:.0f}%  |  T>={MIN_TRADES}  |  "
          f"PnL>=${MIN_REALIZED_PNL}  |  "
          f"Hold {MIN_AVG_HOLD_MIN}-{MAX_AVG_HOLD_MIN}min  |  Aktiv <{DAYS_ACTIVE}d")
    print("=" * 80)
    print(f"  {'Wallet':<46} {'WR%':>5} {'T':>5} {'PnL (USD)':>12} {'Hold':>6}  Status")
    print("  " + "-" * 78)

    for w in filtered:
        status = "vorhanden" if w["wallet"] in current_addrs else "NEU"
        if status == "NEU":
            new_count += 1
        nick     = f" [{w['nickname'][:12]}]" if w["nickname"] else ""
        hold_str = f"{w['avg_hold_min']:.0f}m" if w["avg_hold_min"] > 0 else "?"
        pnl_str  = f"${w['realized_usd']:,.0f}"
        print(f"  {w['wallet']:<46} {w['win_rate']*100:>4.0f}% {w['trades']:>5} "
              f"{pnl_str:>12} {hold_str:>6}  {status}{nick}")

    print()
    print(f"  {new_count} neue Wallets | {len(filtered) - new_count} bereits vorhanden")
    print("=" * 80)
    return new_count


MAX_CANDIDATES = 20  # Maximale Anzahl CandidateWallets in der JSON


def _apply_wallets(filtered: list, current_wallets: list, replace_mode: bool):
    current_addrs = {w["wallet"] for w in current_wallets}

    if replace_mode:
        base        = [w for w in current_wallets if w.get("category") != "CandidateWallet"]
        # Auf MAX_CANDIDATES begrenzen
        new_entries = [{"wallet": w["wallet"], "category": "CandidateWallet", "label": "smart"}
                       for w in filtered[:MAX_CANDIDATES]]
        updated     = base + new_entries
        print(f"[REPLACE] CandidateWallets ersetzt: {len(new_entries)} Eintraege.")
    else:
        # Wie viele Candidates gibt es bereits?
        existing_candidates = [w for w in current_wallets if w.get("category") == "CandidateWallet"]
        free_slots = MAX_CANDIDATES - len(existing_candidates)

        if free_slots <= 0:
            print(f"[APPLY] Candidate-Limit erreicht ({MAX_CANDIDATES}/{MAX_CANDIDATES})."
                  f" Erst evaluate_wallets ausfuehren um Platz zu schaffen.")
            return

        new_entries = [
            {"wallet": w["wallet"], "category": "CandidateWallet", "label": "smart"}
            for w in filtered if w["wallet"] not in current_addrs
        ][:free_slots]  # Nur so viele wie noch Platz ist

        updated = current_wallets + new_entries
        remaining = MAX_CANDIDATES - (len(existing_candidates) + len(new_entries))
        print(f"[APPLY] {len(new_entries)} neue CandidateWallets hinzugefuegt"
              f" ({len(existing_candidates) + len(new_entries)}/{MAX_CANDIDATES} belegt,"
              f" {remaining} Slots frei).")

    backup = WALLETS_FILE.with_suffix(".json.bak")
    if WALLETS_FILE.exists():
        backup.write_bytes(WALLETS_FILE.read_bytes())
        print(f"[APPLY] Backup: {backup.name}")

    WALLETS_FILE.write_text(
        json.dumps(updated, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[APPLY] {WALLETS_FILE.name} aktualisiert ({len(updated)} Wallets gesamt).")


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------

def main():
    args    = sys.argv[1:]
    apply   = "--apply" in args
    replace = False  # --replace absichtlich deaktiviert: bestehende Wallets bleiben immer

    period = PERIOD
    if "--period" in args:
        idx = args.index("--period")
        if idx + 1 < len(args):
            period = args[idx + 1]

    tag = TAG
    if "--tag" in args:
        idx = args.index("--tag")
        if idx + 1 < len(args):
            tag = args[idx + 1]

    rows     = _fetch_gmgn(period, tag, LIMIT)
    current  = _load_current_wallets()
    existing = {w["wallet"] for w in current}
    filtered = _filter_wallets(rows, period, existing_wallets=existing)

    if not filtered:
        print()
        print("[WARN] Keine Wallets nach Filterung uebrig!")
        print("       Tipp: Filter in find_wallets.py anpassen:")
        print(f"         MIN_WIN_RATE     = {MIN_WIN_RATE}  ({MIN_WIN_RATE*100:.0f}%)")
        print(f"         MIN_TRADES       = {MIN_TRADES}")
        print(f"         MIN_REALIZED_PNL = {MIN_REALIZED_PNL}")
        print(f"         MAX_AVG_HOLD_MIN = {MAX_AVG_HOLD_MIN}")
        print(f"         DAYS_ACTIVE      = {DAYS_ACTIVE}")
        sys.exit(0)

    new_count = _print_results(filtered, current, period, tag)

    if not apply:
        print()
        print("  Vorschau-Modus. Zum Anwenden:")
        print("    python find_wallets.py --apply      # Neue hinzufuegen (bestehende bleiben)")
        return

    if new_count == 0 and not replace:
        print("  Alle gefundenen Wallets bereits vorhanden. Nichts zu tun.")
        return

    _apply_wallets(filtered, current, replace_mode=replace)


if __name__ == "__main__":
    main()
