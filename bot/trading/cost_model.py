"""
Transaction Cost Model fuer Solana Meme Coin Trades

Beruecksichtigt alle realen Kosten die beim echten Trading anfallen:

1. Solana Network Fees
   - Base Fee:     0.000005 SOL (~0.0007 EUR bei 150 EUR/SOL)
   - Priority Fee: variabel, typisch 0.0001-0.001 SOL fuer Meme Coins

2. DEX Swap Fees
   - Raydium:  0.25% pro Seite
   - Orca:     0.30% pro Seite
   - Jupiter:  0.00% eigene Fee, aber routet ueber Raydium/Orca

3. Price Impact (AMM x*y=k Modell)
   - Haengt von Pool-Liquiditaet und Positionsgroesse ab
   - Typische Meme Coin Pools: $5K - $200K
   - Positionsgroesse: $50 - $200 EUR
   - Impact = position_size / (pool_liquidity + position_size)

4. Market Drift (Execution Delay)
   - Typische Verzoegerung: 1-3 Sekunden bei Meme Coins
   - Preis kann sich waehrend Execution aendern
   - Drift: ~0.1% - 0.5% bei volatilen Meme Coins

5. Transaction Failure Rate
   - Fehlgeschlagene TXs kosten trotzdem Priority Fee
   - Typisch: 5-15% Failure Rate bei hoher Netzlast
   - Wird als zusaetzlicher Kostenfaktor modelliert

Gesamtkosten pro Seite (realistisches Meme Coin Szenario):
   Pool $10K,  Position $100 EUR → ~4.5% pro Seite → 9% Round-Trip
   Pool $50K,  Position $100 EUR → ~1.3% pro Seite → 2.6% Round-Trip
   Pool $200K, Position $100 EUR → ~0.55% pro Seite → 1.1% Round-Trip
"""

import math
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Konfigurierbare Parameter
# ─────────────────────────────────────────────────────────────────────────────

# Solana Network
SOL_PRICE_EUR          = 150.0        # SOL Preis in EUR (Naehrung, nicht live)
SOL_BASE_FEE           = 0.000005     # SOL pro TX (fest)
SOL_PRIORITY_FEE       = 0.0003       # SOL Prioritaets-Fee (typisch fuer Meme Coins)

# DEX Fees
DEX_SWAP_FEE_RATE      = 0.0025       # 0.25% (Raydium Standard)

# Pool Liquiditaet (EUR) – Schaetzer fuer unbekannte Pools
POOL_LIQUIDITY_DEFAULT_EUR = 30_000   # ~$30K als realistischer Default

# Price Impact Daempfung (je hoeher, desto kleiner der Impact)
# Formel: impact = position / (liquidity * dampening + position)
# dampening = 1.0 → reiner x*y=k Impact
# dampening = 2.0 → haelfte des theoretischen Impacts (schlechtere Schicht)
PRICE_IMPACT_DAMPENING = 2.0

# Market Drift
MARKET_DRIFT_RATE      = 0.002        # 0.2% Preis-Drift durch Execution Delay

# Failure Rate (zusaetzliche Priority Fee durch fehlgeschlagene TXs)
TX_FAILURE_RATE        = 0.10         # 10% fehlgeschlagene TXs

# Minimum/Maximum Gesamtkosten pro Seite (Sicherheitsgrenzen)
MIN_COST_RATE          = 0.003        # Minimum 0.3% pro Seite (nur Fees)
MAX_COST_RATE          = 0.12         # Maximum 12% pro Seite (sehr illiquide)


# ─────────────────────────────────────────────────────────────────────────────
# Cost Breakdown Dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeCost:
    """
    Vollstaendige Kostenaufstellung fuer einen Trade.
    Alle Werte in EUR.
    """
    position_eur:       float   # Positionsgroesse
    pool_liquidity_eur: float   # Geschaetzte Pool-Liquiditaet

    # Komponenten
    network_fee_eur:    float   # Solana Base + Priority Fee
    swap_fee_eur:       float   # DEX Swap Fee (0.25%)
    price_impact_eur:   float   # Preiseinfluss durch Positionsgroesse
    market_drift_eur:   float   # Preis-Drift durch Execution Delay
    failure_cost_eur:   float   # Kosten durch fehlgeschlagene TXs

    # Gesamt
    total_cost_eur:     float   # Summe aller Kosten
    total_cost_rate:    float   # Als Prozentsatz der Positionsgroesse

    def __str__(self) -> str:
        return (
            f"TradeCost: {self.total_cost_eur:.4f} EUR "
            f"({self.total_cost_rate*100:.2f}%) | "
            f"Net={self.network_fee_eur:.4f} "
            f"Swap={self.swap_fee_eur:.4f} "
            f"Impact={self.price_impact_eur:.4f} "
            f"Drift={self.market_drift_eur:.4f}"
        )

    def to_dict(self) -> dict:
        return {
            'position_eur':       round(self.position_eur, 4),
            'pool_liquidity_eur': round(self.pool_liquidity_eur, 2),
            'network_fee_eur':    round(self.network_fee_eur, 6),
            'swap_fee_eur':       round(self.swap_fee_eur, 6),
            'price_impact_eur':   round(self.price_impact_eur, 6),
            'market_drift_eur':   round(self.market_drift_eur, 6),
            'failure_cost_eur':   round(self.failure_cost_eur, 6),
            'total_cost_eur':     round(self.total_cost_eur, 6),
            'total_cost_rate':    round(self.total_cost_rate, 6),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Cost Calculator
# ─────────────────────────────────────────────────────────────────────────────

class TransactionCostModel:
    """
    Berechnet realistische Transaktionskosten fuer Solana Meme Coin Trades.

    Kann mit optionaler Pool-Liquiditaet instanziiert werden.
    Ohne Pool-Liquiditaet wird POOL_LIQUIDITY_DEFAULT_EUR verwendet.

    Verwendung:
        model = TransactionCostModel()

        # Kosten fuer einen BUY berechnen
        cost = model.calculate(position_eur=100.0)
        effective_entry = raw_price * (1 + cost.total_cost_rate)

        # Kosten fuer einen SELL berechnen
        cost = model.calculate(position_eur=100.0)
        effective_exit = raw_price * (1 - cost.total_cost_rate)
    """

    def __init__(
        self,
        pool_liquidity_eur: Optional[float] = None,
        sol_price_eur:      float = SOL_PRICE_EUR,
        swap_fee_rate:      float = DEX_SWAP_FEE_RATE,
        market_drift_rate:  float = MARKET_DRIFT_RATE,
        tx_failure_rate:    float = TX_FAILURE_RATE,
    ):
        self.pool_liquidity_eur = pool_liquidity_eur or POOL_LIQUIDITY_DEFAULT_EUR
        self.sol_price_eur      = sol_price_eur
        self.swap_fee_rate      = swap_fee_rate
        self.market_drift_rate  = market_drift_rate
        self.tx_failure_rate    = tx_failure_rate

        # Netzwerk-Fee pro TX in EUR
        self._base_fee_eur     = SOL_BASE_FEE     * sol_price_eur
        self._priority_fee_eur = SOL_PRIORITY_FEE * sol_price_eur

        logger.debug(
            f"[CostModel] Pool={self.pool_liquidity_eur:.0f} EUR | "
            f"SwapFee={swap_fee_rate*100:.2f}% | "
            f"Drift={market_drift_rate*100:.2f}% | "
            f"FailRate={tx_failure_rate*100:.0f}%"
        )

    def calculate(self, position_eur: float) -> TradeCost:
        """
        Berechnet Transaktionskosten fuer eine Seite (BUY oder SELL).

        Args:
            position_eur: Groesse der Position in EUR

        Returns:
            TradeCost mit allen Kostenkomponenten
        """
        if position_eur <= 0:
            return TradeCost(
                position_eur=position_eur,
                pool_liquidity_eur=self.pool_liquidity_eur,
                network_fee_eur=0, swap_fee_eur=0,
                price_impact_eur=0, market_drift_eur=0,
                failure_cost_eur=0, total_cost_eur=0, total_cost_rate=0
            )

        # 1. Netzwerk-Fee (fix pro TX)
        network_fee = self._base_fee_eur + self._priority_fee_eur

        # 2. DEX Swap Fee (% der Position)
        swap_fee = position_eur * self.swap_fee_rate

        # 3. Price Impact via AMM x*y=k
        #    Bei Kauf: wir erhalten weniger Token als zum aktuellen Preis erwartet
        #    Impact = position / (liquidity * dampening + position)
        #    Das gibt den relativen Preisanstieg durch unseren Kauf an
        price_impact_rate = position_eur / (
            self.pool_liquidity_eur * PRICE_IMPACT_DAMPENING + position_eur
        )
        price_impact = position_eur * price_impact_rate

        # 4. Market Drift (Execution Delay)
        market_drift = position_eur * self.market_drift_rate

        # 5. Failure Cost (fehlgeschlagene TXs zahlen Priority Fee)
        failure_cost = self._priority_fee_eur * self.tx_failure_rate

        # Gesamt
        total_cost = network_fee + swap_fee + price_impact + market_drift + failure_cost
        total_rate = total_cost / position_eur

        # Sicherheitsgrenzen
        total_rate = max(MIN_COST_RATE, min(MAX_COST_RATE, total_rate))
        total_cost = position_eur * total_rate

        cost = TradeCost(
            position_eur       = position_eur,
            pool_liquidity_eur = self.pool_liquidity_eur,
            network_fee_eur    = network_fee,
            swap_fee_eur       = swap_fee,
            price_impact_eur   = price_impact,
            market_drift_eur   = market_drift,
            failure_cost_eur   = failure_cost,
            total_cost_eur     = total_cost,
            total_cost_rate    = total_rate,
        )

        logger.debug(f"[CostModel] {cost}")
        return cost

    def effective_buy_price(self, raw_price: float, position_eur: float) -> tuple:
        """
        Gibt den effektiven Kaufpreis nach Kosten zurueck.
        Der Kaufpreis wird nach oben angepasst (wir zahlen mehr als den Spot-Preis).

        Returns:
            (effective_price, cost)
        """
        cost = self.calculate(position_eur)
        effective = raw_price * (1.0 + cost.total_cost_rate)
        return effective, cost

    def effective_sell_price(self, raw_price: float, position_eur: float) -> tuple:
        """
        Gibt den effektiven Verkaufspreis nach Kosten zurueck.
        Der Verkaufspreis wird nach unten angepasst (wir erhalten weniger als Spot).

        Returns:
            (effective_price, cost)
        """
        cost = self.calculate(position_eur)
        effective = raw_price * (1.0 - cost.total_cost_rate)
        return effective, cost

    def round_trip_cost_rate(self, position_eur: float) -> float:
        """Gesamtkosten fuer BUY + SELL als Prozentsatz."""
        buy_cost  = self.calculate(position_eur)
        sell_cost = self.calculate(position_eur)
        return buy_cost.total_cost_rate + sell_cost.total_cost_rate

    @staticmethod
    def estimate_pool_liquidity(token_address: str) -> float:
        """
        Gibt die Default-Pool-Liquiditaet zurueck.
        Kann spaeter mit DexScreener-Daten befuellt werden.
        """
        return POOL_LIQUIDITY_DEFAULT_EUR

    def summary(self, position_eur: float = 100.0) -> str:
        """Lesbare Zusammenfassung der Kostenstruktur."""
        cost = self.calculate(position_eur)
        return (
            f"Transaktionskosten bei {position_eur:.0f} EUR Position:\n"
            f"  Pool-Liquiditaet:  {self.pool_liquidity_eur:>10,.0f} EUR\n"
            f"  Netzwerk-Fee:      {cost.network_fee_eur:>10.4f} EUR\n"
            f"  DEX Swap-Fee:      {cost.swap_fee_eur:>10.4f} EUR  ({self.swap_fee_rate*100:.2f}%)\n"
            f"  Price Impact:      {cost.price_impact_eur:>10.4f} EUR  ({cost.price_impact_eur/position_eur*100:.2f}%)\n"
            f"  Market Drift:      {cost.market_drift_eur:>10.4f} EUR  ({self.market_drift_rate*100:.2f}%)\n"
            f"  Failure Cost:      {cost.failure_cost_eur:>10.4f} EUR\n"
            f"  ─────────────────────────────────────\n"
            f"  Gesamt pro Seite:  {cost.total_cost_eur:>10.4f} EUR  ({cost.total_cost_rate*100:.2f}%)\n"
            f"  Round-Trip:        {self.round_trip_cost_rate(position_eur)*100:.2f}%\n"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Globale Default-Instanz
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_COST_MODEL = TransactionCostModel()


# ─────────────────────────────────────────────────────────────────────────────
# Quick-Test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Transaction Cost Model - Szenarien ===\n")

    scenarios = [
        ("Sehr illiquide  (Pool $5K)",   5_000),
        ("Illiquide       (Pool $10K)",  10_000),
        ("Durchschnitt    (Pool $30K)",  30_000),
        ("Liquide         (Pool $100K)", 100_000),
        ("Sehr liquide    (Pool $200K)", 200_000),
    ]

    for label, liquidity in scenarios:
        model = TransactionCostModel(pool_liquidity_eur=liquidity)
        for pos in [50, 100, 200]:
            cost = model.calculate(pos)
            rt   = model.round_trip_cost_rate(pos)
            print(f"{label} | Pos={pos:>3} EUR | "
                  f"pro Seite: {cost.total_cost_rate*100:.2f}% | "
                  f"Round-Trip: {rt*100:.2f}%")
        print()

    print("\n=== Default Model (Pool $30K, Position $100 EUR) ===\n")
    print(DEFAULT_COST_MODEL.summary(100.0))
