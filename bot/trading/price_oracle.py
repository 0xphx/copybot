"""
Price Oracle - Holt Token Preise in EUR
Nutzt Jupiter, Birdeye und CoinGecko
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
        self.session: Optional[aiohttp.ClientSession] = None
        self.fetch_count = 0
        self.hit_count = 0
        self.miss_count = 0
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Gibt aktive Session zurück oder erstellt neue"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def get_price_eur(self, token_address: str, skip_cache: bool = False) -> Optional[float]:
        """Holt Preis in EUR für Token"""
        
        # Cache check (skip wenn Force Refresh)
        if not skip_cache and token_address in self.cache:
            self.hit_count += 1
            return self.cache[token_address]
        
        self.fetch_count += 1
        
        # Versuche Jupiter API v6
        price = await self._fetch_from_jupiter_v6(token_address)
        
        if price is None:
            # Fallback: Jupiter Lite (alternativer Endpoint)
            price = await self._fetch_from_jupiter_lite(token_address)

        if price is None:
            # Fallback: DexScreener (kein API Key nötig, sehr zuverlässig)
            price = await self._fetch_from_dexscreener(token_address)

        if price is None:
            # Fallback: Birdeye
            price = await self._fetch_from_birdeye(token_address)
        
        if price is None:
            # Fallback: CoinGecko (nur bekannte Tokens)
            price = await self._fetch_from_coingecko(token_address)
        
        if price is None:
            logger.warning(f"[PriceOracle] No price found for {token_address[:8]}..., using mock price")
            price = 0.01
            self.miss_count += 1
        
        self.cache[token_address] = price
        return price
    
    async def _fetch_from_jupiter_v6(self, token_address: str) -> Optional[float]:
        """Holt Preis von Jupiter Price API v2"""
        try:
            session = await self._get_session()
            url = f"https://api.jup.ag/price/v2?ids={token_address}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    logger.debug(f"[PriceOracle] Jupiter v2 HTTP {response.status} for {token_address[:8]}...")
                    return None
                
                data = await response.json()
                
                if "data" not in data:
                    logger.debug(f"[PriceOracle] Jupiter v2 no 'data' key: {data}")
                    return None

                token_data = data["data"].get(token_address)
                if token_data is None:
                    logger.debug(f"[PriceOracle] Jupiter v2 token not found in response")
                    return None
                
                price_usd_str = token_data.get("price")
                if price_usd_str is None:
                    logger.debug(f"[PriceOracle] Jupiter v2 no 'price' field: {token_data}")
                    return None
                
                price_usd = float(price_usd_str)
                if price_usd == 0:
                    return None

                price_eur = price_usd * 0.92
                logger.info(f"[PriceOracle] ✅ Jupiter: {token_address[:8]}... = {price_eur:.8f} EUR (${price_usd:.8f})")
                return price_eur
                
        except Exception as e:
            logger.debug(f"[PriceOracle] Jupiter v2 failed: {type(e).__name__}: {e}")
            return None

    async def _fetch_from_jupiter_lite(self, token_address: str) -> Optional[float]:
        """Holt Preis von Jupiter Lite API (alternativer Endpoint)"""
        try:
            session = await self._get_session()
            # Lite API - direkter Quote gegen USDC
            usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            url = f"https://lite-api.jup.ag/price/v2?ids={token_address}&vsToken={usdc}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                token_data = data.get("data", {}).get(token_address)
                if not token_data:
                    return None

                price_usd_str = token_data.get("price")
                if not price_usd_str:
                    return None

                price_usd = float(price_usd_str)
                if price_usd == 0:
                    return None

                price_eur = price_usd * 0.92
                logger.info(f"[PriceOracle] ✅ Jupiter Lite: {token_address[:8]}... = {price_eur:.8f} EUR")
                return price_eur

        except Exception as e:
            logger.debug(f"[PriceOracle] Jupiter Lite failed: {type(e).__name__}: {e}")
            return None

    async def _fetch_from_dexscreener(self, token_address: str) -> Optional[float]:
        """Holt Preis von DexScreener (kein API Key nötig, sehr zuverlässig für Solana Memecoins)"""
        try:
            session = await self._get_session()
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    logger.debug(f"[PriceOracle] DexScreener HTTP {response.status}")
                    return None
                
                data = await response.json()
                pairs = data.get("pairs")
                
                if not pairs or len(pairs) == 0:
                    logger.debug(f"[PriceOracle] DexScreener no pairs for {token_address[:8]}...")
                    return None
                
                # Nimm das Pair mit höchstem Liquidity (erstes = meist bestes)
                # Filtere nur Solana Pairs
                sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                if not sol_pairs:
                    sol_pairs = pairs  # Fallback: alle Pairs
                
                # Sortiere nach Liquidity
                sol_pairs.sort(key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
                best_pair = sol_pairs[0]
                
                price_usd_str = best_pair.get("priceUsd")
                if not price_usd_str:
                    return None
                
                price_usd = float(price_usd_str)
                if price_usd == 0:
                    return None

                price_eur = price_usd * 0.92
                logger.info(f"[PriceOracle] ✅ DexScreener: {token_address[:8]}... = {price_eur:.8f} EUR (${price_usd:.8f})")
                return price_eur
                
        except Exception as e:
            logger.debug(f"[PriceOracle] DexScreener failed: {type(e).__name__}: {e}")
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
                    logger.debug(f"[PriceOracle] Birdeye HTTP {response.status}")
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
                logger.info(f"[PriceOracle] ✅ Birdeye: {token_address[:8]}... = {price_eur:.8f} EUR")
                return price_eur
                
        except Exception as e:
            logger.debug(f"[PriceOracle] Birdeye failed: {type(e).__name__}: {e}")
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
                logger.info(f"[PriceOracle] ✅ CoinGecko: {token_address[:8]}... = {price_eur:.6f} EUR")
                return price_eur
                
        except Exception as e:
            logger.debug(f"[PriceOracle] CoinGecko failed: {type(e).__name__}: {e}")
            return None
    
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
        print("📊 Price Oracle Statistics:")
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
