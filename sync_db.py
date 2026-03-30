"""
sync_db.py - Synchronisiert die data/*.db Dateien ueber ein separates Git-Repo.

Setup (einmalig):
  1. Erstelle ein neues privates GitHub Repo (z.B. "copybot-data")
  2. python sync_db.py setup https://github.com/DEIN_USER/copybot-data.git

Danach:
  python sync_db.py push    # DB hochladen (nach einer Session)
  python sync_db.py pull    # DB herunterladen (vor einer Session)
  python sync_db.py status  # Zeigt ob lokale DB neuer oder aelter ist
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime

# Pfade
SCRIPT_DIR  = Path(__file__).parent
DATA_DIR    = SCRIPT_DIR / "bot" / "data"
SYNC_DIR    = SCRIPT_DIR / ".db_sync"   # lokaler Klon des data-Repos
CONFIG_FILE = SCRIPT_DIR / ".db_sync_remote"

DB_FILES = [
    "wallet_performance.db",
    "observer_performance.db",
    "axiom.db",
]


def _run(cmd: list, cwd=None, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd or SYNC_DIR,
        capture_output=True, text=True, check=check
    )


def _git(*args, check=True):
    return _run(["git"] + list(args), check=check)


def _get_remote() -> str:
    if not CONFIG_FILE.exists():
        print("[ERROR] Kein Remote konfiguriert.")
        print("        Fuehre zuerst aus: python sync_db.py setup <REPO_URL>")
        sys.exit(1)
    return CONFIG_FILE.read_text().strip()


def cmd_setup(remote_url: str):
    """Initialisiert das Sync-Repo einmalig."""
    CONFIG_FILE.write_text(remote_url)

    if SYNC_DIR.exists():
        print(f"[INFO] {SYNC_DIR} existiert bereits, ueberspringe clone.")
    else:
        print(f"[SETUP] Klone {remote_url} nach {SYNC_DIR} ...")
        _run(["git", "clone", remote_url, str(SYNC_DIR)], cwd=SCRIPT_DIR)
        print("[SETUP] Klon erfolgreich.")

    # .gitignore im Sync-Repo anlegen falls nicht vorhanden
    gi = SYNC_DIR / ".gitignore"
    if not gi.exists():
        gi.write_text("# Nur .db Dateien tracken\n*\n!*.db\n!.gitignore\n")
        _git("add", ".gitignore")
        _git("commit", "-m", "init: gitignore", check=False)
        _git("push", "origin", "main", check=False)
        _git("push", "origin", "master", check=False)

    print("[SETUP] Fertig. Nutze jetzt:")
    print("  python sync_db.py push   # nach einer Session")
    print("  python sync_db.py pull   # vor einer Session")


def cmd_push():
    """Kopiert lokale DBs ins Sync-Repo und pusht."""
    _get_remote()
    if not SYNC_DIR.exists():
        print("[ERROR] Sync-Repo nicht initialisiert. Fuehre setup aus.")
        sys.exit(1)

    # Erst pullen um Konflikte zu vermeiden
    print("[PUSH] Hole neuesten Stand vom Remote ...")
    _git("pull", "--rebase", "origin", check=False)

    # DBs kopieren
    copied = []
    for db in DB_FILES:
        src = DATA_DIR / db
        dst = SYNC_DIR / db
        if src.exists():
            shutil.copy2(src, dst)
            copied.append(db)
            size_kb = src.stat().st_size // 1024
            print(f"  Kopiert: {db} ({size_kb} KB)")

    if not copied:
        print("[PUSH] Keine DB-Dateien gefunden in", DATA_DIR)
        sys.exit(1)

    # Commit + Push
    _git("add", *[str(SYNC_DIR / db) for db in copied])

    hostname = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg      = f"sync: {hostname} {ts}"

    result = _git("commit", "-m", msg, check=False)
    if "nothing to commit" in result.stdout + result.stderr:
        print("[PUSH] Keine Aenderungen - DB ist bereits aktuell.")
        return

    # Branch ermitteln
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    _git("push", "origin", branch)
    print(f"[PUSH] Erfolgreich gepusht: {msg}")


def cmd_pull():
    """Pullt neueste DBs aus dem Sync-Repo und kopiert sie lokal."""
    _get_remote()
    if not SYNC_DIR.exists():
        print("[ERROR] Sync-Repo nicht initialisiert. Fuehre setup aus.")
        sys.exit(1)

    print("[PULL] Hole neuesten Stand vom Remote ...")
    _git("pull", "--rebase", "origin")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    updated = []
    for db in DB_FILES:
        src = SYNC_DIR / db
        dst = DATA_DIR / db
        if src.exists():
            # Backup der lokalen DB
            if dst.exists():
                backup = DATA_DIR / f"{db}.bak"
                shutil.copy2(dst, backup)
            shutil.copy2(src, dst)
            updated.append(db)
            size_kb = src.stat().st_size // 1024
            print(f"  Aktualisiert: {db} ({size_kb} KB)")

    if not updated:
        print("[PULL] Keine DB-Dateien im Remote-Repo gefunden.")
    else:
        print(f"[PULL] {len(updated)} Datei(en) aktualisiert. Backup als *.bak gespeichert.")


def cmd_status():
    """Zeigt ob lokale DBs neuer oder aelter als Remote sind."""
    _get_remote()
    if not SYNC_DIR.exists():
        print("[STATUS] Sync-Repo nicht initialisiert.")
        sys.exit(1)

    _git("fetch", "origin", check=False)

    print("[STATUS] DB-Dateien:")
    print(f"  {'Datei':<35} {'Lokal':<22} {'Remote (gecacht)'}")
    print("  " + "-" * 75)

    for db in DB_FILES:
        local  = DATA_DIR / db
        remote = SYNC_DIR / db

        local_ts  = datetime.fromtimestamp(local.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")  if local.exists()  else "nicht vorhanden"
        remote_ts = datetime.fromtimestamp(remote.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if remote.exists() else "nicht vorhanden"

        if local.exists() and remote.exists():
            diff = local.stat().st_mtime - remote.stat().st_mtime
            if abs(diff) < 60:
                flag = "= gleich"
            elif diff > 0:
                flag = "^ lokal neuer"
            else:
                flag = "v remote neuer"
        else:
            flag = ""

        print(f"  {db:<35} {local_ts:<22} {remote_ts}  {flag}")

    # Letzter Commit im Sync-Repo
    log = _git("log", "--oneline", "-3", check=False)
    if log.returncode == 0 and log.stdout.strip():
        print("\n  Letzte Commits im Sync-Repo:")
        for line in log.stdout.strip().splitlines():
            print(f"    {line}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "setup":
        if len(sys.argv) < 3:
            print("[ERROR] URL fehlt: python sync_db.py setup <REPO_URL>")
            sys.exit(1)
        cmd_setup(sys.argv[2])
    elif cmd == "push":
        cmd_push()
    elif cmd == "pull":
        cmd_pull()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"[ERROR] Unbekannter Befehl: {cmd}")
        print("Verfuegbar: setup, push, pull, status")
        sys.exit(1)


if __name__ == "__main__":
    main()
