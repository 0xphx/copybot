#repository = Persistenz

from db.database import get_connection
from axiom.models import AxiomWallet

def upsert_wallet(wallet: AxiomWallet):
    with get_connection() as conn:
        conn.execute("""
        INSERT INTO axiom_wallets (wallet, category, source, active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(wallet) DO UPDATE SET
            category=excluded.category,
            active=excluded.active,
            last_updated=CURRENT_TIMESTAMP
        """, (
            wallet.wallet,
            wallet.category,
            wallet.source,
            int(wallet.active)
        ))
