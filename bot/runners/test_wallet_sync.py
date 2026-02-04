from db.database import init_db
from wallets.sync import sync_wallets

def run():
    # DB initialisieren
    init_db()

    # Wallet Sync ausführen
    wallets = sync_wallets()

    # Ergebnis ausgeben
    for w in wallets:
        print(w)
