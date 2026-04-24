#!/usr/bin/env python3
"""
deploy.py - Copybot auf einem neuen Server einrichten

Aufruf: python deploy.py

Fragt nach IP und User, verbindet via SSH und:
  1. Installiert Python + pip
  2. Kopiert den Bot-Code
  3. Installiert alle Python-Packages
  4. Registriert das Geraet fuer Auto-Sync
  5. Richtet screen ein damit der Bot 24/7 laeuft
"""

import subprocess
import sys
import os
import json
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
DEVICES_FILE = SCRIPT_DIR / ".devices.json"
BOT_DIR      = SCRIPT_DIR / "bot"


# ──────────────────────────────────────────────────────────────────────────────
# Geraete-Registry
# ──────────────────────────────────────────────────────────────────────────────

def load_devices() -> list:
    if not DEVICES_FILE.exists():
        return []
    try:
        return json.loads(DEVICES_FILE.read_text())
    except Exception:
        return []


def save_devices(devices: list):
    DEVICES_FILE.write_text(json.dumps(devices, indent=2))


def add_device(user: str, host: str, label: str):
    devices = load_devices()
    for d in devices:
        if d["host"] == host and d["user"] == user:
            print(f"  Geraet {label} ({user}@{host}) bereits registriert.")
            return
    devices.append({"user": user, "host": host, "label": label})
    save_devices(devices)
    print(f"  Geraet registriert: {label} ({user}@{host})")


def list_devices():
    devices = load_devices()
    if not devices:
        print("  Keine Geraete registriert.")
        return
    print(f"  {'Nr':<4} {'Label':<20} {'User@Host'}")
    print("  " + "-" * 50)
    for i, d in enumerate(devices, 1):
        print(f"  {i:<4} {d['label']:<20} {d['user']}@{d['host']}")


# ──────────────────────────────────────────────────────────────────────────────
# SSH Hilfsfunktionen
# ──────────────────────────────────────────────────────────────────────────────

def ssh_run(user: str, host: str, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Fuehrt einen Befehl per SSH aus."""
    full_cmd = ["ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{user}@{host}", cmd]
    return subprocess.run(full_cmd, capture_output=False, check=check)


def scp_push(user: str, host: str, local: str, remote: str):
    """Kopiert eine Datei/Verzeichnis zum Server."""
    cmd = ["scp", "-r", "-o", "StrictHostKeyChecking=no", local, f"{user}@{host}:{remote}"]
    subprocess.run(cmd, check=True)


def scp_pull(user: str, host: str, remote: str, local: str):
    """Kopiert eine Datei/Verzeichnis vom Server."""
    cmd = ["scp", "-r", "-o", "StrictHostKeyChecking=no", f"{user}@{host}:{remote}", local]
    subprocess.run(cmd, check=True)


def test_connection(user: str, host: str) -> bool:
    """Prueft ob SSH-Verbindung moeglich ist."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=5", f"{user}@{host}", "echo ok"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Deploy
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Server-Checks
# ──────────────────────────────────────────────────────────────────────────────

MIN_PYTHON_VERSION = (3, 10)   # mindestens 3.10 wegen moderner Syntax
MIN_DISK_GB        = 1.0       # mindestens 1 GB freier Speicher
MIN_RAM_MB         = 256       # mindestens 256 MB RAM


def ssh_output(user: str, host: str, cmd: str) -> str:
    """Fuehrt SSH-Befehl aus und gibt stdout als String zurueck."""
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10", f"{user}@{host}", cmd],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def check_server(user: str, host: str) -> bool:
    """
    Prueft den Server auf alle Voraussetzungen.
    Gibt True zurueck wenn alles OK oder reparierbar ist.
    Gibt False zurueck wenn ein kritisches Problem vorliegt.
    """
    print("  [2/6] Server pruefen ...")
    ok    = True
    fixes = []   # Befehle die automatisch ausgefuehrt werden sollen

    # -- Python --
    raw = ssh_output(user, host, "python3 --version 2>/dev/null || echo MISSING")
    if "MISSING" in raw or not raw:
        print("       Python:     nicht installiert  -> wird installiert")
        fixes.append("sudo apt-get install -y python3 python3-pip")
    else:
        try:
            parts   = raw.replace("Python ", "").split(".")
            version = (int(parts[0]), int(parts[1]))
            if version < MIN_PYTHON_VERSION:
                min_str = ".".join(str(v) for v in MIN_PYTHON_VERSION)
                print(f"       Python:     {raw}  ->  zu alt (mind. {min_str} benoetigt)")
                print(f"       FEHLER: Python-Version zu alt - bitte manuell updaten:")
                print(f"         sudo apt-get install -y python3.11")
                ok = False
            else:
                print(f"       Python:     {raw}  OK")
        except Exception:
            print(f"       Python:     {raw}  (Version nicht parsebar - fahre fort)")

    # -- pip --
    raw = ssh_output(user, host, "pip3 --version 2>/dev/null || echo MISSING")
    if "MISSING" in raw or not raw:
        print("       pip3:       nicht installiert  -> wird installiert")
        fixes.append("sudo apt-get install -y python3-pip")
    else:
        print("       pip3:       installiert  OK")

    # -- screen --
    raw = ssh_output(user, host, "screen --version 2>/dev/null || echo MISSING")
    if "MISSING" in raw or not raw:
        print("       screen:     nicht installiert  -> wird installiert")
        fixes.append("sudo apt-get install -y screen")
    else:
        print("       screen:     installiert  OK")

    # -- rsync --
    raw = ssh_output(user, host, "rsync --version 2>/dev/null || echo MISSING")
    if "MISSING" in raw or not raw:
        print("       rsync:      nicht installiert  -> wird installiert")
        fixes.append("sudo apt-get install -y rsync")
    else:
        print("       rsync:      installiert  OK")

    # -- git --
    raw = ssh_output(user, host, "git --version 2>/dev/null || echo MISSING")
    if "MISSING" in raw or not raw:
        print("       git:        nicht installiert  -> wird installiert")
        fixes.append("sudo apt-get install -y git")
    else:
        print("       git:        installiert  OK")

    # -- Speicherplatz --
    raw = ssh_output(user, host, "df -BG / | awk 'NR==2 {print $4}'")
    try:
        free_gb = float(raw.replace("G", "").strip())
        if free_gb < MIN_DISK_GB:
            print(f"       Speicher:   {free_gb:.1f} GB frei  ->  WARNUNG (mind. {MIN_DISK_GB} GB empfohlen)")
        else:
            print(f"       Speicher:   {free_gb:.1f} GB frei  OK")
    except Exception:
        print("       Speicher:   nicht ermittelbar")

    # -- RAM --
    raw = ssh_output(user, host, "free -m | awk 'NR==2 {print $7}'")
    try:
        free_mb = int(raw.strip())
        if free_mb < MIN_RAM_MB:
            print(f"       RAM frei:   {free_mb} MB  ->  WARNUNG (mind. {MIN_RAM_MB} MB empfohlen)")
        else:
            print(f"       RAM frei:   {free_mb} MB  OK")
    except Exception:
        print("       RAM:        nicht ermittelbar")

    # -- Fixes ausfuehren --
    if fixes:
        print()
        print("       Installiere fehlende Pakete ...")
        all_fixes = "sudo apt-get update -qq && " + " && ".join(fixes)
        ssh_run(user, host, all_fixes, check=False)
        print("       Installation abgeschlossen")

    return ok


# ──────────────────────────────────────────────────────────────────────────────
# Deploy
# ──────────────────────────────────────────────────────────────────────────────

def deploy(user: str, host: str, label: str):
    """Richtet den Bot auf einem neuen Server ein."""
    print()
    print(f"  Deploying auf {user}@{host} ...")
    print()

    # 1. Verbindung testen
    print("  [1/6] Verbindung testen ...")
    if not test_connection(user, host):
        print(f"  FEHLER: Kann nicht zu {user}@{host} verbinden.")
        print("  Stelle sicher dass:")
        print("   - Der Server lauft und erreichbar ist")
        print("   - SSH aktiviert ist")
        print("   - Du im gleichen Netzwerk bist (bei lokaler IP)")
        return False

    print("       Verbindung OK")

    # 2. Server pruefen (Python, pip, screen, rsync, git, Speicher, RAM)
    if not check_server(user, host):
        print()
        print("  FEHLER: Server-Check fehlgeschlagen. Deploy abgebrochen.")
        return False

    # 3. Code kopieren
    print("  [3/6] Code kopieren ...")
    ssh_run(user, host, "mkdir -p ~/copybot/bot/data")
    scp_push(user, host, str(BOT_DIR), "~/copybot/")
    print("       Code kopiert")

    # 4. Requirements installieren
    print("  [4/6] Python-Packages installieren ...")
    req_file = BOT_DIR / "requirements.txt"
    if req_file.exists():
        ssh_run(user, host, "cd ~/copybot/bot && pip3 install -r requirements.txt -q")
    else:
        ssh_run(user, host, "pip3 install aiohttp websockets requests -q")
    print("       Packages installiert")

    # 5. Datenbanken synchronisieren (falls vorhanden)
    print("  [5/6] Datenbanken kopieren ...")
    data_dir = BOT_DIR / "data"
    synced = 0
    for db_file in ["observer_performance.db", "wallet_performance.db"]:
        local_db = data_dir / db_file
        if local_db.exists():
            scp_push(user, host, str(local_db), f"~/copybot/bot/data/{db_file}")
            size_kb = local_db.stat().st_size // 1024
            print(f"       {db_file} ({size_kb} KB)")
            synced += 1
    if synced == 0:
        print("       Keine lokalen DBs gefunden (frischer Start)")

    # 6. Geraet registrieren
    print("  [6/6] Geraet registrieren ...")
    add_device(user, host, label)

    print()
    print("  ✓ Deploy abgeschlossen!")
    print()
    print("  Bot starten:")
    print(f"    ssh {user}@{host}")
    print(f"    screen -S copybot")
    print(f"    cd ~/copybot/bot && python3 main.py wallet_analysis")
    print(f"    # Strg+A, dann D  ->  Session im Hintergrund lassen")
    print()
    print("  Bot-Output spaeter anzeigen:")
    print(f"    ssh {user}@{host}")
    print(f"    screen -r copybot")
    print()
    return True


def update_device(user: str, host: str, label: str):
    """Fuehrt git pull + pip install auf einem Server aus."""
    print(f"  Update {label} ({user}@{host}) ...")

    if not test_connection(user, host):
        print(f"  {label}: nicht erreichbar - uebersprungen")
        return False

    # git pull
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{host}",
         "cd ~/copybot && git pull 2>&1"],
        capture_output=True, text=True
    )
    output = result.stdout.strip()
    if "Already up to date" in output:
        print(f"  {label}: bereits aktuell")
    elif "error" in output.lower() or result.returncode != 0:
        print(f"  {label}: git pull Fehler: {output[:80]}")
        return False
    else:
        print(f"  {label}: Code aktualisiert")
        # Nur wenn Code geaendert wurde: pip install
        req = ssh_output(user, host, "test -f ~/copybot/bot/requirements.txt && echo YES || echo NO")
        if req == "YES":
            ssh_run(user, host, "cd ~/copybot/bot && pip3 install -r requirements.txt -q", check=False)
            print(f"  {label}: Packages aktualisiert")

    return True


def update_all():
    """Fuehrt git pull + pip install auf allen registrierten Geraeten aus."""
    devices = load_devices()
    if not devices:
        print("  Keine Geraete registriert.")
        return
    print()
    print(f"[Update] Aktualisiere {len(devices)} Geraet(e) ...")
    for d in devices:
        update_device(d["user"], d["host"], d["label"])
    print()


# ──────────────────────────────────────────────────────────────────────────────
# Sync
# ──────────────────────────────────────────────────────────────────────────────

def sync_dbs_from_device(user: str, host: str, label: str):
    """Holt DBs von einem Geraet und merged sie lokal."""
    print(f"  Hole DBs von {label} ({user}@{host}) ...")
    data_dir  = BOT_DIR / "data"
    tmp_dir   = SCRIPT_DIR / ".sync_tmp"
    tmp_dir.mkdir(exist_ok=True)

    pulled = []
    for db_file in ["observer_performance.db", "wallet_performance.db"]:
        remote_path = f"~/copybot/bot/data/{db_file}"
        tmp_path    = tmp_dir / f"{label}_{db_file}"
        try:
            scp_pull(user, host, remote_path, str(tmp_path))
            pulled.append((db_file, tmp_path))
            print(f"    {db_file} geholt")
        except Exception as e:
            print(f"    {db_file} nicht verfuegbar ({type(e).__name__})")

    return pulled


def merge_db(local_db: Path, remote_db: Path):
    """
    Merged Sessions aus remote_db in local_db.
    Importiert nur Sessions die lokal noch nicht vorhanden sind.
    """
    import sqlite3

    if not remote_db.exists():
        return 0

    local_db.parent.mkdir(parents=True, exist_ok=True)

    conn_remote = sqlite3.connect(str(remote_db))
    conn_local  = sqlite3.connect(str(local_db)) if local_db.exists() else sqlite3.connect(str(local_db))
    conn_local.row_factory = sqlite3.Row

    cur_remote = conn_remote.cursor()
    cur_local  = conn_local.cursor()

    # Tabellen aus Remote in Local kopieren falls nicht vorhanden
    cur_remote.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='wallet_trades'")
    row = cur_remote.fetchone()
    if not row:
        conn_remote.close()
        conn_local.close()
        return 0

    cur_local.execute("""
        CREATE TABLE IF NOT EXISTS wallet_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, wallet TEXT, token TEXT, side TEXT,
            amount REAL, price_eur REAL, value_eur REAL, pnl_eur REAL,
            pnl_percent REAL, price_missing INTEGER, max_price_pct REAL,
            min_price_pct REAL, timestamp TEXT, reason TEXT
        )
    """)

    # Bestehende Session-IDs lokal
    cur_local.execute("SELECT DISTINCT session_id FROM wallet_trades")
    existing = {r[0] for r in cur_local.fetchall()}

    # Neue Sessions aus Remote importieren
    cur_remote.execute("SELECT DISTINCT session_id FROM wallet_trades")
    remote_sessions = [r[0] for r in cur_remote.fetchall()]
    new_sessions    = [s for s in remote_sessions if s not in existing]

    imported = 0
    for session_id in new_sessions:
        cur_remote.execute("SELECT * FROM wallet_trades WHERE session_id = ?", (session_id,))
        rows = cur_remote.fetchall()
        for row in rows:
            row_dict = dict(zip([d[0] for d in cur_remote.description], row))
            row_dict.pop("id", None)
            cols = ", ".join(row_dict.keys())
            vals = ", ".join(["?" for _ in row_dict])
            cur_local.execute(f"INSERT INTO wallet_trades ({cols}) VALUES ({vals})", list(row_dict.values()))
        imported += len(rows)

    # wallet_stats neu berechnen fuer neue Sessions (vereinfacht: einfach aus wallet_trades)
    cur_local.execute("""
        CREATE TABLE IF NOT EXISTS wallet_stats (
            wallet TEXT PRIMARY KEY,
            total_trades INTEGER, winning_trades INTEGER, losing_trades INTEGER,
            total_pnl_eur REAL, avg_pnl_eur REAL, win_rate REAL,
            confidence_score REAL, last_updated TEXT, strategy_label TEXT,
            price_missing_count INTEGER, dynamic_sl REAL, dynamic_tp REAL
        )
    """)

    conn_local.commit()
    conn_remote.close()
    conn_local.close()
    return imported


def sync_all(push_after: bool = True):
    """Synchronisiert DBs mit allen registrierten Geraeten."""
    devices = load_devices()
    if not devices:
        return

    print()
    print(f"[Sync] Synchronisiere mit {len(devices)} Geraet(en) ...")

    tmp_dir = SCRIPT_DIR / ".sync_tmp"
    tmp_dir.mkdir(exist_ok=True)

    data_dir = BOT_DIR / "data"
    total_imported = 0

    for device in devices:
        user  = device["user"]
        host  = device["host"]
        label = device["label"]

        # Verbindung pruefen
        if not test_connection(user, host):
            print(f"[Sync] {label} ({user}@{host}) nicht erreichbar - uebersprungen")
            continue

        # DBs vom Geraet holen und mergen
        pulled = sync_dbs_from_device(user, host, label)
        for db_file, tmp_path in pulled:
            local_db = data_dir / db_file
            n = merge_db(local_db, tmp_path)
            if n > 0:
                print(f"[Sync] {label}: {n} neue Eintraege aus {db_file} importiert")
            else:
                print(f"[Sync] {label}: {db_file} - keine neuen Sessions")
            total_imported += n

        # Aktualisierte DBs zurueck pushen
        if push_after:
            for db_file in ["observer_performance.db", "wallet_performance.db"]:
                local_db = data_dir / db_file
                if local_db.exists():
                    try:
                        scp_push(user, host, str(local_db), f"~/copybot/bot/data/{db_file}")
                    except Exception:
                        pass

    # Temp-Dateien aufraeumen
    import shutil
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    if total_imported > 0:
        print(f"[Sync] Gesamt {total_imported} neue Eintraege importiert")
    else:
        print(f"[Sync] Alle Geraete sind synchron")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args:
        # Interaktiver Modus
        print()
        print("=" * 55)
        print("  COPYBOT DEPLOY")
        print("=" * 55)
        print()
        print("  Registrierte Geraete:")
        list_devices()
        print()
        print("  Optionen:")
        print("   [1]  Neues Geraet einrichten")
        print("   [2]  DBs jetzt synchronisieren")
        print("   [3]  Code-Update auf alle Geraete (git pull)")
        print("   [4]  Geraete anzeigen")
        print("   [q]  Beenden")
        print()

        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if choice == "1":
            print()
            try:
                host  = input("  Server IP:   ").strip()
                user  = input("  SSH User:    ").strip()
                label = input("  Label (z.B. 'heimserver'): ").strip() or host
            except (EOFError, KeyboardInterrupt):
                print()
                return
            deploy(user, host, label)

        elif choice == "2":
            sync_all()

        elif choice == "3":
            update_all()

        elif choice == "4":
            print()
            list_devices()
            print()

        return

    cmd = args[0].lower()

    if cmd == "deploy":
        if len(args) >= 3:
            host  = args[1]
            user  = args[2]
            label = args[3] if len(args) > 3 else host
        else:
            host  = input("  Server IP:   ").strip()
            user  = input("  SSH User:    ").strip()
            label = input("  Label:       ").strip() or host
        deploy(user, host, label)

    elif cmd == "sync":
        sync_all()

    elif cmd == "update":
        update_all()

    elif cmd == "devices":
        list_devices()

    else:
        print(f"  Unbekannter Befehl: {cmd}")
        print("  Verfuegbar: deploy, sync, devices")


if __name__ == "__main__":
    main()
