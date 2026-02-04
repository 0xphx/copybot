import json
import sqlite3
from pathlib import Path

DB_PATH = "data/axiom.db"


def load_wallets_from_json(json_path: str) -> None:
    """
    Lädt Wallets aus einer JSON-Datei in die axiom_wallets Tabelle.

    Design:
    - Die JSON ist die Quelle der Wahrheit für diesen Import
    - Die Tabelle wird vor dem Import geleert
    - Der Import ist idempotent (gleiches Input → gleicher DB-Zustand)

    Erwartetes JSON-Format:
    [
        { "wallet": "<address>", "category": "<string>" },
        ...
    ]
    """

    path = Path(json_path)

    # --- Validierung: Datei vorhanden?
    if not path.exists():
        raise FileNotFoundError(f"Axiom JSON not found: {json_path}")

    # --- JSON laden
    with path.open("r", encoding="utf-8") as f:
        wallets = json.load(f)

    if not isinstance(wallets, list):
        raise ValueError("Axiom JSON must be a list of wallet objects")

    # --- DB verbinden
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- Transaktion starten (wichtig!)
    # Alles oder nichts → verhindert kaputte DB-Zustände
    try:
        # Alte Daten entfernen
        cursor.execute("DELETE FROM axiom_wallets")

        # Wallets einfügen
        for entry in wallets:
            wallet = entry.get("wallet")
            category = entry.get("category")

            # Minimal-Validierung
            if not wallet:
                raise ValueError(f"Invalid wallet entry: {entry}")

            cursor.execute(
                """
                INSERT INTO axiom_wallets (wallet, category, active)
                VALUES (?, ?, 1)
                """,
                (wallet, category)
            )

        # Änderungen dauerhaft speichern
        conn.commit()

        print(f"[Axiom Loader] Imported {len(wallets)} wallets from {json_path}")

    except Exception:
        # Bei Fehler → alles zurückrollen
        conn.rollback()
        raise

    finally:
        conn.close()
