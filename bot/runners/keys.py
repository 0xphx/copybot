"""
Keys Runner - Helius API Keys verwalten
Aufruf: python main.py keys

Fragt beim Start automatisch den aktuellen Credit-Stand
direkt von Helius ab (1 Test-Request pro Key, kostet 1 Credit).
"""
import sys
import re
import urllib.request
import json

NETWORK_FILE      = "config/network.py"
CREDITS_PER_MONTH = 1_000_000
REQUESTS_PER_DAY  = 277_000   # ca. Bedarf bei 60 Wallets, 5s Intervall

# Header-Namen die Helius fuer verbleibende Credits sendet (Reihenfolge = Prioritaet)
REMAINING_HEADERS = [
    "x-ratelimit-remaining-month",
    "x-credits-remaining",
    "ratelimit-remaining",
    "x-ratelimit-remaining",
]


# ──────────────────────────────────────────────────────────────────────────────
# Config lesen / schreiben
# ──────────────────────────────────────────────────────────────────────────────

def load_keys() -> list:
    try:
        with open(NETWORK_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'HELIUS_API_KEYS\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if not match:
            return []
        block = match.group(1)
        keys = []
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            m = re.search(r'"([^"]+)"', stripped)
            if m:
                keys.append(m.group(1))
        return keys
    except FileNotFoundError:
        return []


def save_keys(keys: list) -> bool:
    try:
        with open(NETWORK_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        lines     = [f'    "{key}",  # Key {i}' for i, key in enumerate(keys, 1)]
        new_block = "HELIUS_API_KEYS = [\n" + "\n".join(lines) + "\n]"
        new_content = re.sub(
            r'HELIUS_API_KEYS\s*=\s*\[.*?\]', new_block,
            content, flags=re.DOTALL
        )
        with open(NETWORK_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"  Fehler beim Speichern: {e}")
        return False


def validate_key(key: str) -> bool:
    pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    return bool(re.match(pattern, key.strip(), re.IGNORECASE))


# ──────────────────────────────────────────────────────────────────────────────
# Live Credit-Abfrage
# ──────────────────────────────────────────────────────────────────────────────

def fetch_remaining_credits(key: str) -> tuple:
    """
    Sendet einen minimalen getVersion-Request an Helius und liest
    die verbleibenden Credits aus dem Response-Header.

    Gibt (remaining: int | None, error: str | None) zurueck.
    getVersion kostet 1 Credit und ist die guenstigste Abfrage.
    """
    url     = f"https://mainnet.helius-rpc.com/?api-key={key}"
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getVersion", "params": []}).encode()
    req     = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            for hdr in REMAINING_HEADERS:
                val = headers.get(hdr)
                if val is not None:
                    try:
                        return int(val), None
                    except (ValueError, TypeError):
                        pass
            # Header nicht vorhanden - Body pruefen ob Key valide
            body = json.loads(resp.read())
            if "result" in body:
                return None, "unbekannt"
            return None, "Unbekannte Antwort"

    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None, "Ungueltiger Key (401)"
        if e.code == 429:
            try:
                body = json.loads(e.read().decode())
                msg  = body.get("error", {}).get("message", "").lower()
            except Exception:
                msg = ""
            if "max usage" in msg:
                return 0, "ERSCHOEPFT"
            # Temporaeres Rate-Limit (zu viele Requests gerade)
            return None, "Rate-Limit (kurz warten)"
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:40]}"


def check_all_keys(keys: list) -> list:
    """
    Fragt fuer jeden Key den aktuellen Credit-Stand ab.
    Gibt Liste von dicts: {key, remaining, error} zurueck.
    """
    results = []
    for key in keys:
        remaining, error = fetch_remaining_credits(key)
        results.append({"key": key, "remaining": remaining, "error": error})
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Ausgabe
# ──────────────────────────────────────────────────────────────────────────────

def print_keys(keys: list, credit_results: list = None):
    """Gibt Key-Liste mit Credit-Stand aus."""
    total_month = len(keys) * CREDITS_PER_MONTH

    print()
    print("=" * 62)
    print("  HELIUS API KEYS")
    print("=" * 62)

    if not keys:
        print("  (keine Keys konfiguriert)")
        print()
    else:
        for i, key in enumerate(keys, 1):
            masked = f"{key[:8]}...{key[-4:]}"
            if credit_results and i - 1 < len(credit_results):
                r = credit_results[i - 1]
                if r["error"] == "ERSCHOEPFT" and r["remaining"] == 0:
                    credit_str = "   leer"
                elif r["error"] == "unbekannt":
                    credit_str = "   aktiv"
                elif r["error"] and r["remaining"] is None:
                    credit_str = f"  FEHLER: {r['error']}"
                elif r["remaining"] is not None:
                    pct        = (r["remaining"] / CREDITS_PER_MONTH * 100)
                    credit_str = f"  {r['remaining']:>9,} verbleibend  ({pct:.0f}%)"
                else:
                    credit_str = f"  {r['error']}"
            else:
                credit_str = "  (nicht abgefragt)"
            print(f"  [{i}]  {masked}{credit_str}")
        print()

    # Gesamtzusammenfassung
    print(f"  Keys gesamt:     {len(keys)}")
    print(f"  Limit/Monat:     {total_month:,}  ({CREDITS_PER_MONTH:,} pro Key)")
    print(f"  Bedarf/Tag:      ~{REQUESTS_PER_DAY:,}  (60 Wallets, 5s Intervall)")

    print()
    print("  Neue Keys:  https://dev.helius.xyz/dashboard")
    print("=" * 62)


# ──────────────────────────────────────────────────────────────────────────────
# Haupt-Loop
# ──────────────────────────────────────────────────────────────────────────────

def run(args=None):
    print()

    # Beim ersten Aufruf Credits live abfragen
    keys           = load_keys()
    credit_results = None

    if keys:
        credit_results = check_all_keys(keys)

    while True:
        keys = load_keys()
        print_keys(keys, credit_results)

        print("  Optionen:")
        print("   [a]  Key hinzufuegen")
        if keys:
            print("   [r]  Credits aktualisieren")
            print("   [d]  Key loeschen")
            print("   [s]  Keys vollstaendig anzeigen")
        print("   [q]  Beenden")
        print()

        try:
            raw = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw in ("q", "quit", "exit", ""):
            break

        # ── Credits aktualisieren ────────────────────────────────────
        elif raw == "r":
            if not keys:
                continue
            credit_results = check_all_keys(keys)

        # ── Key hinzufuegen ──────────────────────────────────────────
        elif raw == "a":
            print()
            print("  Neuen Helius API Key eingeben")
            print("  (Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)")
            print("  Leere Eingabe = abbrechen")
            print()
            try:
                new_key = input("  Key: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue

            if not new_key:
                print("  Abgebrochen.")
                continue

            if not validate_key(new_key):
                print()
                print("  Ungueltig: Key muss im UUID-Format sein")
                input("  [ENTER] weiter")
                continue

            if new_key in keys:
                print()
                print("  Dieser Key ist bereits eingetragen.")
                input("  [ENTER] weiter")
                continue

            # Neuen Key direkt pruefen
            print(f"  Pruefe neuen Key ...")
            remaining, error = fetch_remaining_credits(new_key)
            if error and remaining is None and "OK" not in (error or ""):
                print(f"  Warnung: {error}")
                try:
                    confirm = input("  Trotzdem hinzufuegen? [j/N]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    continue
                if confirm not in ("j", "ja", "y", "yes"):
                    print("  Abgebrochen.")
                    continue

            keys.append(new_key)
            if save_keys(keys):
                masked = f"{new_key[:8]}...{new_key[-4:]}"
                if remaining is not None:
                    print(f"  Key {masked} hinzugefuegt.  {remaining:,} Credits verbleibend.")
                else:
                    print(f"  Key {masked} hinzugefuegt.")
                # Credit-Results aktualisieren
                if credit_results is None:
                    credit_results = []
                credit_results.append({"key": new_key, "remaining": remaining, "error": error})
            input("  [ENTER] weiter")

        # ── Key loeschen ─────────────────────────────────────────────
        elif raw == "d":
            if not keys:
                continue
            print()
            print("  Welchen Key loeschen? (Nummer, leere Eingabe = abbrechen)")
            print()
            for i, key in enumerate(keys, 1):
                print(f"  [{i}]  {key[:8]}...{key[-4:]}")
            print()
            try:
                nr_raw = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue

            if not nr_raw:
                print("  Abgebrochen.")
                continue

            try:
                nr = int(nr_raw)
            except ValueError:
                print("  Ungueltige Eingabe.")
                input("  [ENTER] weiter")
                continue

            if nr < 1 or nr > len(keys):
                print(f"  Nummer muss zwischen 1 und {len(keys)} liegen.")
                input("  [ENTER] weiter")
                continue

            removed = keys.pop(nr - 1)
            if credit_results and nr - 1 < len(credit_results):
                credit_results.pop(nr - 1)
            if save_keys(keys):
                print(f"  Key {removed[:8]}...{removed[-4:]} entfernt.")
                if not keys:
                    print("  WARNUNG: Keine Keys mehr konfiguriert!")
            input("  [ENTER] weiter")

        # ── Keys vollstaendig anzeigen ────────────────────────────────
        elif raw == "s":
            if not keys:
                continue
            print()
            print("  Vollstaendige Keys (vertraulich - nicht weitergeben!):")
            print()
            for i, key in enumerate(keys, 1):
                print(f"  [{i}]  {key}")
            print()
            input("  [ENTER] weiter")

        else:
            print(f"  Unbekannte Eingabe: '{raw}'")

    print()
