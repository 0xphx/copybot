"""
Price Oracle - Holt Token Preise in EUR
Waterfall: DexScreener  Birdeye  CoinGecko
Jupiter v2 / Lite wurden entfernt (erfordern API Key  HTTP 401/404)
"""
import aiohttp
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PriceOracle:
    """Holt Token Preise in EUR"""
    
    # Bekannte Token mit CoinGecko IDs
    KNOWN_TOKENS = {
        "So11111111111111111111111111111111111111112": "solana",  # SOL
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "usd-coin",  # USDC
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "tether",  # USDT
    }
    
    def __init__(self):
        self.cache: Dict[str, float] = {}
        self.cache_time: Dict[str, float] = {}   # token → timestamp des letzten Fetches
        self.session: Optional[aiohttp.ClientSession] = None
        self.fetch_count = 0
        self.hit_count = 0
        self.miss_count = 0

        # Minimale Cache-Zeit bei skip_cache=True (verhindert API-Spam)
        # Wird dynamisch gesetzt via set_rate_limit_from_positions()
        self.min_cache_seconds: float = 0.5

        # Limit für DexScreener (Requests/Min)
        self._api_rate_limit: int = 280  # knapp unter 300 als Puffer
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Gibt aktive Session zurück oder erstellt neue"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def get_price_eur(self, token_address: str, skip_cache: bool = False) -> Optional[float]:
        """
        Holt Preis in EUR für Token.
        Gibt None zurück wenn kein echter Preis gefunden wurde  kein Mock-Fallback.
        """
        import time

        # Normaler Cache
        if not skip_cache and token_address in self.cache:
            self.hit_count += 1
            return self.cache[token_address]

        # Minimaler Cache auch bei skip_cache – verhindert API-Spam
        if skip_cache and self.min_cache_seconds > 0 and token_address in self.cache_time:
            age = time.monotonic() - self.cache_time[token_address]
            if age < self.min_cache_seconds:
                self.hit_count += 1
                return self.cache[token_address]
        
        self.fetch_count += 1

        sources = [
            ("DexScreener", self._fetch_from_dexscreener),
            ("Birdeye",     self._fetch_from_birdeye),
            ("CoinGecko",   self._fetch_from_coingecko),
        ]

        for name, fetch_fn in sources:
            price = await fetch_fn(token_address)
            if price is not None:
                self.cache[token_address] = price
                self.cache_time[token_address] = time.monotonic()
                return price
            logger.warning(f"[PriceOracle]  {name}  no price for {token_address[:8]}...")

        logger.warning(f"[PriceOracle]   All sources failed for {token_address[:8]}...  skipping (no mock)")
        self.miss_count += 1
        return None

    async def _fetch_from_dexscreener(self, token_address: str) -> Optional[float]:
        """Holt Preis von DexScreener (kein API Key nötig, sehr zuverlässig für Solana Memecoins)"""
        try:
            session = await self._get_session()
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    logger.warning(f"[PriceOracle] DexScreener HTTP {response.status}")
                    return None
                
                data = await response.json()
                pairs = data.get("pairs")
                
                if not pairs or len(pairs) == 0:
                    logger.debug(f"[PriceOracle] DexScreener no pairs for {token_address[:8]}...")
                    return None
                
                sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                if not sol_pairs:
                    sol_pairs = pairs
                
                sol_pairs.sort(key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
                best_pair = sol_pairs[0]
                
                price_usd_str = best_pair.get("priceUsd")
                if not price_usd_str:
                    return None
                
                price_usd = float(price_usd_str)
                if price_usd == 0:
                    return None

                price_eur = price_usd * 0.92
                logger.info(f"[PriceOracle]  DexScreener: {token_address[:8]}... = {price_eur:.8f} EUR (${price_usd:.8f})")
                return price_eur
                
        except Exception as e:
            logger.warning(f"[PriceOracle] DexScreener exception: {type(e).__name__}: {e}")
            return None

    async def _fetch_from_birdeye(self, token_address: str) -> Optional[float]:
        """Holt Preis von Birdeye"""
        try:
            session = await self._get_session()
            url = f"https://public-api.birdeye.so/defi/price?address={token_address}"
            
            async with session.get(
                url,
                headers={"X-CHAIN": "solana"},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as response:
                if response.status != 200:
                    logger.warning(f"[PriceOracle] Birdeye HTTP {response.status}")
                    return None
                
                data = await response.json()
                
                if not data.get("success"):
                    return None

                price_usd = data.get("data", {}).get("value")
                if price_usd is None:
                    return None
                
                price_usd = float(price_usd)
                if price_usd == 0:
                    return None

                price_eur = price_usd * 0.92
                logger.info(f"[PriceOracle]  Birdeye: {token_address[:8]}... = {price_eur:.8f} EUR")
                return price_eur
                
        except Exception as e:
            logger.warning(f"[PriceOracle] Birdeye exception: {type(e).__name__}: {e}")
            return None
    
    async def _fetch_from_coingecko(self, token_address: str) -> Optional[float]:
        """Holt Preis von CoinGecko (nur bekannte Tokens)"""
        try:
            if token_address not in self.KNOWN_TOKENS:
                return None
            
            coin_id = self.KNOWN_TOKENS[token_address]
            session = await self._get_session()
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=eur"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                
                if coin_id not in data or "eur" not in data[coin_id]:
                    return None
                
                price_eur = float(data[coin_id]["eur"])
                logger.info(f"[PriceOracle]  CoinGecko: {token_address[:8]}... = {price_eur:.6f} EUR")
                return price_eur
                
        except Exception as e:
            logger.warning(f"[PriceOracle] CoinGecko exception: {type(e).__name__}: {e}")
            return None
    
    def set_rate_limit_from_positions(self, open_positions: int):
        """
        Passt min_cache_seconds dynamisch an die Anzahl offener Positionen an.
        Ziel: immer knapp unter 280 Requests/Min bleiben.

        Formel: cache = positions / rate_limit * 60
        Beispiele:
          1 Position  → 0.21s Cache → ~280 Req/Min
          3 Positionen → 0.64s Cache → ~280 Req/Min
          5 Positionen → 1.07s Cache → ~280 Req/Min
         10 Positionen → 2.14s Cache → ~280 Req/Min
        """
        n = max(1, open_positions)
        self.min_cache_seconds = round(n / self._api_rate_limit * 60, 3)
        logger.debug(
            f"[PriceOracle] Rate limit adjusted: "
            f"{n} positions → min_cache={self.min_cache_seconds:.2f}s "
            f"(~{self._api_rate_limit} req/min)"
        )

    async def get_multiple_prices(self, token_addresses: list) -> Dict[str, float]:
        """Holt mehrere Preise gleichzeitig"""
        prices = {}
        for token in token_addresses:
            price = await self.get_price_eur(token)
            if price:
                prices[token] = price
        return prices
    
    async def close(self):
        """Schließt HTTP Session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    def clear_cache(self):
        """Löscht Preis Cache"""
        self.cache.clear()
        logger.debug("[PriceOracle] Cache cleared")
    
    def print_all_stats(self):
        """Gibt Statistiken aus"""
        print(" Price Oracle Statistics:")
        print(f"   Total Fetches:    {self.fetch_count}")
        print(f"   Cache Hits:       {self.hit_count}")
        print(f"   API Misses:       {self.miss_count}")
        if self.fetch_count > 0:
            print(f"   Success Rate:     {((self.fetch_count - self.miss_count) / self.fetch_count * 100):.1f}%")


class MockPriceOracle(PriceOracle):
    """Mock Oracle für Testing mit dynamischen Preisen"""
    
    def __init__(self, mock_prices: Dict[str, float] = None):
        super().__init__()
        self.mock_prices = mock_prices or {}
    
    async def get_price_eur(self, token_address: str, skip_cache: bool = False) -> Optional[float]:
        """Gibt Mock-Preis zurück mit Variation"""
        import random
        if token_address in self.mock_prices:
            price = self.mock_prices[token_address]
        else:
            price = random.uniform(0.001, 10.0)
            self.mock_prices[token_address] = price
        
        variation = random.uniform(0.98, 1.02)
        final_price = price * variation
        
        logger.debug(f"[MockPriceOracle] {token_address[:8]}... = {final_price:.6f} EUR")
        return final_price
    
    def set_price(self, token_address: str, price_eur: float):
        self.mock_prices[token_address] = price_eur
    
    def simulate_price_change(self, token_address: str, change_percent: float):
        if token_address in self.mock_prices:
            current = self.mock_prices[token_address]
            new_price = current * (1 + change_percent / 100)
            self.mock_prices[token_address] = new_price
            logger.info(
                f"[MockPriceOracle] {token_address[:8]}... "
                f"{current:.6f} EUR -> {new_price:.6f} EUR ({change_percent:+.1f}%)"
            )
