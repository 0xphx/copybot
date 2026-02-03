from dataclasses import dataclass

# Repräsentiert eine Wallet, die aktiv beobachtet wird
# Diese Struktur ist das Output-Format des Wallet Sync Layers
# und der Input für den Trade Observation Layer
@dataclass
class ActiveWallet:
    # Public Solana Wallet Address
    wallet: str

    # Kategorie aus Axiom (z. B. "Top Trader", "Momentum")
    # Wird später für Gewichtung / Filter genutzt
    category: str | None

    # Gewicht der Wallet für Pattern-Scoring
    # V1: statisch = 1.0
    # V2: dynamisch (Performance, Winrate, etc.)
    weight: float
