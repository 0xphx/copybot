import sqlite3
from typing import List
from wallets.models import ActiveWallet

# Pfad zur SQLite DB
# Wichtig: relativer Pfad, damit der Code portabel bleibt
DB_PATH = "data/axiom.db"

def load_active_wallets(
    categories: list[str] | None = None,
    limit: int | None = None
) -> List[ActiveWallet]:
    """
    Lädt aktive Wallets aus der DB.

    Diese Funktion ist absichtlich "dumm":
    - sie filtert nur nach DB-Feldern
    - sie enthält KEINE Business-Logik
    """

    # Verbindung zur DB öffnen
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Basis-Query:
    # Nur Wallets, die aktiv markiert sind
    query = """
        SELECT wallet, category
        FROM axiom_wallets
        WHERE active = 1
    """
    params = []

    # Optionaler Filter nach Kategorien
    # Vorteil: Wallet Sync kann steuern, welche Gruppen aktiv sind
    if categories:
        placeholders = ",".join("?" for _ in categories)
        query += f" AND category IN ({placeholders})"
        params.extend(categories)

    # Optionales Limit
    # Schutz vor zu vielen beobachteten Wallets
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    # Query ausführen
    cursor.execute(query, params)
    rows = cursor.fetchall()

    # DB-Verbindung schließen (wichtig bei SQLite)
    conn.close()

    wallets = []

    # Jede DB-Zeile in ein ActiveWallet-Objekt umwandeln
    for wallet, category in rows:
        wallets.append(
            ActiveWallet(
                wallet=wallet,
                category=category,
                weight=1.0  # V1: konstantes Gewicht
            )
        )

    return wallets
