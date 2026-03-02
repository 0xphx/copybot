"""
Realistic Mock Price Oracle - Simuliert realistische Krypto-Preise
Basiert auf echten Solana Token Statistiken
"""
import random
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RealisticMockOracle:
    """
    Simuliert realistische Token-Preise mit Schwankungen
    Basiert auf echten Solana Meme Coin Statistiken
    """
    
    # Realistische Preis-Ranges basierend auf echten Solana Meme Coins
    PRICE_TEMPLATES = {
        "micro": {  # 0.0001 - 0.001 EUR (wie BONK, PEPE)
            "base_min": 0.0001,
            "base_max": 0.001,
            "volatility": 0.15,  # ±15% pro Update
            "trend_bias": 0.02,  # Leichter Aufwärtstrend
        },
        "small": {  # 0.001 - 0.01 EUR
            "base_min": 0.001,
            "base_max": 0.01,
            "volatility": 0.12,
            "trend_bias": 0.01,
        },
        "medium": {  # 0.01 - 0.10 EUR
            "base_min": 0.01,
            "base_max": 0.10,
            "volatility": 0.10,
            "trend_bias": 0.005,
        },
        "large": {  # 0.10 - 1.00 EUR
            "base_min": 0.10,
            "base_max": 1.00,
            "volatility": 0.08,
            "trend_bias": 0.0,
        },
        "xlarge": {  # 1.00 - 10.00 EUR
            "base_min": 1.00,
            "base_max": 10.00,
            "volatility": 0.06,
            "trend_bias": -0.005,  # Leichter Abwärtstrend (mean reversion)
        }
    }
    
    def __init__(self):
        self.prices: Dict[str, float] = {}
        self.price_history: Dict[str, list] = {}
        self.token_templates: Dict[str, str] = {}  # token -> template
        self.last_update: Dict[str, datetime] = {}
        
        logger.info("[RealisticMockOracle] Initialized with realistic price simulation")
    
    async def get_price_eur(self, token_address: str) -> Optional[float]:
        """Holt realistischen Preis mit Schwankungen"""
        
        # Neues Token → Initialisiere
        if token_address not in self.prices:
            self._initialize_token(token_address)
        
        # Update Preis mit realistischer Volatilität
        self._update_price(token_address)
        
        price = self.prices[token_address]
        logger.debug(f"[RealisticMockOracle] {token_address[:8]}... = {price:.6f} EUR")
        
        return price
    
    def _initialize_token(self, token_address: str):
        """Initialisiert neues Token mit realistischem Startpreis"""
        
        # Wähle Template basierend auf Hash
        template_options = list(self.PRICE_TEMPLATES.keys())
        # Verwende Token-Hash für konsistente Zuordnung
        hash_val = hash(token_address) % len(template_options)
        template_name = template_options[hash_val]
        
        template = self.PRICE_TEMPLATES[template_name]
        self.token_templates[token_address] = template_name
        
        # Zufälliger Startpreis innerhalb Range
        base_price = random.uniform(template["base_min"], template["base_max"])
        
        self.prices[token_address] = base_price
        self.price_history[token_address] = [base_price]
        self.last_update[token_address] = datetime.now()
        
        logger.info(
            f"[RealisticMockOracle] New token {token_address[:8]}... "
            f"initialized at {base_price:.6f} EUR (template: {template_name})"
        )
    
    def _update_price(self, token_address: str):
        """Updated Preis mit realistischer Volatilität"""
        
        now = datetime.now()
        last_update = self.last_update.get(token_address, now)
        
        # Update nur alle 5+ Sekunden
        if (now - last_update).total_seconds() < 5:
            return
        
        template_name = self.token_templates[token_address]
        template = self.PRICE_TEMPLATES[template_name]
        
        current_price = self.prices[token_address]
        
        # Realistische Preisbewegung
        # 1. Zufällige Schwankung (Volatilität)
        volatility = template["volatility"]
        random_change = random.gauss(0, volatility)  # Normal-Verteilung
        
        # 2. Trend Bias
        trend = template["trend_bias"]
        
        # 3. Mean Reversion (zu Mitte der Range)
        range_mid = (template["base_min"] + template["base_max"]) / 2
        distance_from_mid = (current_price - range_mid) / range_mid
        mean_reversion = -distance_from_mid * 0.05  # 5% pull zur Mitte
        
        # Kombiniere alle Faktoren
        total_change = random_change + trend + mean_reversion
        
        # Neue Preis
        new_price = current_price * (1 + total_change)
        
        # Begrenze auf Template-Range (mit etwas Spielraum)
        min_price = template["base_min"] * 0.5
        max_price = template["base_max"] * 2.0
        new_price = max(min_price, min(max_price, new_price))
        
        # Update
        self.prices[token_address] = new_price
        self.price_history[token_address].append(new_price)
        self.last_update[token_address] = now
        
        # Log bei signifikanter Änderung
        change_pct = ((new_price - current_price) / current_price) * 100
        if abs(change_pct) >= 5:
            emoji = "📈" if change_pct > 0 else "📉"
            logger.info(
                f"[RealisticMockOracle] {emoji} {token_address[:8]}... "
                f"{current_price:.6f} → {new_price:.6f} EUR ({change_pct:+.2f}%)"
            )
    
    async def get_multiple_prices(self, token_addresses: list) -> Dict[str, float]:
        """Holt mehrere Preise"""
        prices = {}
        for token in token_addresses:
            price = await self.get_price_eur(token)
            if price:
                prices[token] = price
        return prices
    
    async def close(self):
        """Cleanup"""
        pass
    
    def get_price_stats(self, token_address: str) -> dict:
        """Gibt Statistiken für Token zurück"""
        if token_address not in self.price_history:
            return {}
        
        history = self.price_history[token_address]
        if not history:
            return {}
        
        current = history[-1]
        start = history[0]
        change = ((current - start) / start) * 100
        
        return {
            "current": current,
            "start": start,
            "min": min(history),
            "max": max(history),
            "change_percent": change,
            "updates": len(history),
            "template": self.token_templates.get(token_address, "unknown")
        }
    
    def print_all_stats(self):
        """Zeigt Stats für alle Tokens"""
        print("\n" + "="*70)
        print("📊 TOKEN PRICE STATISTICS")
        print("="*70)
        
        for token in sorted(self.prices.keys()):
            stats = self.get_price_stats(token)
            if not stats:
                continue
            
            emoji = "📈" if stats["change_percent"] > 0 else "📉"
            print(f"\n{emoji} {token[:12]}... ({stats['template']})")
            print(f"   Current:  {stats['current']:.6f} EUR")
            print(f"   Start:    {stats['start']:.6f} EUR")
            print(f"   Range:    {stats['min']:.6f} - {stats['max']:.6f} EUR")
            print(f"   Change:   {stats['change_percent']:+.2f}%")
            print(f"   Updates:  {stats['updates']}")
        
        print("="*70)
