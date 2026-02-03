import sqlite3
from pathlib import Path

DB_PATH = Path("data/axiom.db")
DB_PATH.parent.mkdir(exist_ok=True)

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS axiom_wallets (
            wallet TEXT PRIMARY KEY,
            category TEXT,
            source TEXT,
            active INTEGER,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
