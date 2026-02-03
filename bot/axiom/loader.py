#loader = Quelle

import json
from axiom.models import AxiomWallet
from axiom.repository import upsert_wallet

def load_wallets_from_json(path: str):
    with open(path, "r") as f:
        data = json.load(f)

    for entry in data:
        wallet = AxiomWallet(
            wallet=entry["wallet"],
            category=entry.get("category")
        )
        upsert_wallet(wallet)
