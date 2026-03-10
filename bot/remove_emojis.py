"""
remove_emojis.py
----------------
Entfernt alle Emojis aus allen .py-Dateien im angegebenen Verzeichnis.
Alles andere (Leerzeichen, Einrückungen, Kommentare, Logik) bleibt unverändert.

Usage:
    python remove_emojis.py                    # Arbeitet im aktuellen Verzeichnis
    python remove_emojis.py C:/pfad/zum/bot    # Arbeitet im angegebenen Verzeichnis
    python remove_emojis.py --dry-run          # Nur anzeigen, nichts schreiben
"""

import re
import sys
import os


# Unicode-Ranges die Emojis abdecken
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbole & Piktogramme
    "\U0001F680-\U0001F6FF"  # Transport & Karten
    "\U0001F700-\U0001F7FF"  # Alchemische Symbole, geometrische Formen
    "\U0001F800-\U0001F8FF"  # Ergänzende Pfeile
    "\U0001F900-\U0001F9FF"  # Ergänzende Symbole & Piktogramme
    "\U0001FA00-\U0001FA6F"  # Schach, Sonstiges
    "\U0001FA70-\U0001FAFF"  # Weitere Ergänzungen
    "\U0001F1E0-\U0001F1FF"  # Flaggen-Buchstaben
    "\U00002600-\U000026FF"  # Verschiedene Symbole (   etc.)
    "\U00002700-\U000027BF"  # Dingbats
    "\U00002300-\U000023FF"  # Technische Symbole (  etc.)
    "\U00002B00-\U00002BFF"  # Verschiedene Symbole & Pfeile (  etc.)
    "\U00002500-\U000025FF"  # Box-Drawing & geometrische Formen (  etc.)
    "\U00002000-\U000020CF"  # Allgemeine Interpunktion (Vorsicht  normal lassen)
    "\U00003000-\U000030FF"  # CJK Symbole
    "\U0000FE00-\U0000FE0F"  # Variation Selectors (Emoji-Modifier)
    "\U00002100-\U000021FF"  # Buchstaben-ähnliche Symbole (  etc.)
    "]+",
    flags=re.UNICODE
)


def remove_emojis_from_text(text: str) -> str:
    return EMOJI_PATTERN.sub("", text)


def process_file(filepath: str, dry_run: bool = False) -> bool:
    """
    Verarbeitet eine einzelne Datei.
    Gibt True zurück wenn die Datei geändert wurde (oder werden würde).
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()

    cleaned = remove_emojis_from_text(original)

    if cleaned == original:
        return False  # Keine Änderung nötig

    if not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(cleaned)

    return True


def find_py_files(root_dir: str):
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # .venv / venv / __pycache__ überspringen
        dirnames[:] = [
            d for d in dirnames
            if d not in {"__pycache__", ".venv", "venv", "env", ".git", "node_modules"}
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def main():
    # Args parsen
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    root_dir = args[0] if args else "."
    root_dir = os.path.abspath(root_dir)

    if not os.path.isdir(root_dir):
        print(f"Fehler: '{root_dir}' ist kein gültiges Verzeichnis.")
        sys.exit(1)

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"{'='*55}")
    print(f"  Emoji Remover [{mode}]")
    print(f"  Verzeichnis: {root_dir}")
    print(f"{'='*55}")

    changed = []
    unchanged = []

    for filepath in find_py_files(root_dir):
        was_changed = process_file(filepath, dry_run=dry_run)
        rel = os.path.relpath(filepath, root_dir)
        if was_changed:
            changed.append(rel)
            status = "WÜRDE ÄNDERN" if dry_run else "GEÄNDERT    "
            print(f"   {status}  {rel}")
        else:
            unchanged.append(rel)

    print(f"{'='*55}")
    print(f"  Dateien geprüft:   {len(changed) + len(unchanged)}")
    print(f"  Dateien geändert:  {len(changed)}")
    print(f"  Ohne Emojis:       {len(unchanged)}")
    if dry_run:
        print(f"\n  (Dry Run  keine Datei wurde geschrieben)")
        print(f"  Ohne --dry-run nochmal ausführen zum Anwenden.")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
