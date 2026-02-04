from db.database import init_db
from axiom.loader import load_wallets_from_json

def run():
    """
    Lädt Wallet-Daten aus Axiom JSON in die Datenbank.
    Einmalig oder manuell aufrufbar.
    """

    init_db()
    load_wallets_from_json("data/axiom_wallets.json")
    print("[Axiom Import] Wallets loaded.")
