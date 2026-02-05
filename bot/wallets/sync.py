from wallets.repository import load_active_wallets
from wallets.models import ActiveWallet

def sync_wallets() -> list[ActiveWallet]:
    """
    Zentrale Kontrollstelle für:
    - welche Wallets beobachtet werden
    - in welcher Anzahl
    - aus welchen Kategorien

    Diese Funktion ist die SINGLE SOURCE OF TRUTH
    für den Trade Observation Layer.
    """

    # Wallets aus der DB laden
    # Kategorien & Limit sind bewusst hier und nicht im Repository
    wallets = load_active_wallets(
        categories=["Top Trader", "PaperWallet", "OwnWallet"],  # konfigurierbare Auswahl
        limit=50                                # Hard Cap für V1
    )

    # Deduplizierung (Sicherheitsnetz)
    # Falls Wallets mehrfach in DB auftauchen sollten
    unique = {}
    for w in wallets:
        unique[w.wallet] = w

    # In Liste umwandeln
    active_wallets = list(unique.values())

    # Logging für Debugging & Monitoring
    print(f"[WalletSync] Active wallets: {len(active_wallets)}")

    # Rückgabe an den nächsten Layer
    return active_wallets
