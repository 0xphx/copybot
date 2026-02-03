from db.database import init_db
from axiom.loader import load_wallets_from_json

if __name__ == "__main__":
    init_db()
    load_wallets_from_json("data/axiom_wallets.json")
    print("Axiom wallets loaded.")
