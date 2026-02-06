"""
Solana Polling Source - Alternative zu WebSocket Subscriptions
Fragt regelmäßig Wallet-Transaktionen ab und erkennt Trades
"""
import asyncio
import json
import logging
from typing import Optional, Dict, Set
from datetime import datetime
import aiohttp

from observation.models import TradeEvent
from .base import TradeSource

logger = logging.getLogger(__name__)


# Bekannte "Währungs"-Tokens
CURRENCY_MINTS = {
    "So11111111111111111111111111111111111111112",  # Wrapped SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}


class SolanaPollingSource(TradeSource):
    """
    Polling-basierte Trade Detection für Solana
    
    Funktionsweise:
    1. Alle X Sekunden: Hole neueste Transactions für jede Wallet
    2. Vergleiche Signatures mit bereits gesehenen
    3. Neue Transactions → Parse & Emit Trade Events
    """

    def __init__(
        self,
        rpc_http_url: str,
        wallets: list[str] = None,
        callback=None,
        poll_interval: int = 2,  # Sekunden zwischen Abfragen
    ):
        super().__init__()
        self.rpc_http_url = rpc_http_url
        self.wallets = list(wallets or [])
        self.poll_interval = poll_interval
        self.seen_signatures: Set[str] = set()  # Bereits verarbeitete Transactions
        self.running = False
        
        print(f"[Polling] Poll interval: {poll_interval}s")
        print(f"[Polling] Watching {len(self.wallets)} wallets")
        
        if callback:
            self.on_trade = callback


    async def connect(self):
        """Startet Polling Loop"""
        self.running = True
        logger.info(f"[Polling] Starting with {len(self.wallets)} wallets")
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            try:
                while self.running:
                    await self.poll_all_wallets()
                    await asyncio.sleep(self.poll_interval)
                    
            except asyncio.CancelledError:
                logger.info("[Polling] Cancelled, stopping...")
                self.running = False
                raise


    async def poll_all_wallets(self):
        """Fragt alle Wallets gleichzeitig ab"""
        tasks = [self.poll_wallet(wallet) for wallet in self.wallets]
        await asyncio.gather(*tasks, return_exceptions=True)


    async def poll_wallet(self, wallet: str):
        """
        Fragt neueste Transactions einer Wallet ab
        
        API Call: getSignaturesForAddress
        Gibt Liste der neuesten Transaction Signatures zurück
        """
        try:
            # Request Body
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    wallet,
                    {"limit": 5}  # Nur die letzten 5 Transactions
                ]
            }
            
            async with self.session.post(
                self.rpc_http_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json()
                
                if "error" in data:
                    logger.error(f"[Polling] RPC Error for {wallet[:8]}...: {data['error']}")
                    return
                
                signatures = data.get("result", [])
                
                # Neue Signatures finden
                new_sigs = []
                for sig_info in signatures:
                    sig = sig_info.get("signature")
                    if sig and sig not in self.seen_signatures:
                        new_sigs.append(sig)
                        self.seen_signatures.add(sig)
                
                if new_sigs:
                    logger.info(f"[Polling] {wallet[:8]}... has {len(new_sigs)} new transactions")
                    
                    # Hole Details für neue Transactions
                    for sig in new_sigs:
                        await self.fetch_and_process_transaction(sig, wallet)
                        
        except asyncio.TimeoutError:
            logger.warning(f"[Polling] Timeout for wallet {wallet[:8]}...")
        except Exception as e:
            logger.error(f"[Polling] Error polling wallet {wallet[:8]}...: {e}")


    async def fetch_and_process_transaction(self, signature: str, wallet: str):
        """
        Holt Transaction Details und verarbeitet sie
        
        API Call: getTransaction
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            
            async with self.session.post(
                self.rpc_http_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json()
                
                if "error" in data:
                    logger.debug(f"[Polling] Could not fetch tx {signature[:8]}...")
                    return
                
                tx = data.get("result")
                if not tx:
                    return
                
                # Trade extrahieren
                trade_event = self.extract_trade(tx, wallet, signature)
                if trade_event:
                    await self.emit_trade(trade_event)
                    
        except Exception as e:
            logger.error(f"[Polling] Error fetching transaction {signature[:8]}...: {e}")


    def extract_trade(self, tx: dict, wallet: str, signature: str) -> Optional[TradeEvent]:
        """
        Extrahiert Trade Information aus Transaction
        
        Schaut auf Token Balance Änderungen (pre vs post)
        """
        try:
            meta = tx.get("meta", {})
            
            # Pre/Post Token Balances
            pre_balances = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])
            
            if not pre_balances and not post_balances:
                return None
            
            # Balance Maps: {mint: amount}
            pre = {}
            post = {}
            
            for balance in pre_balances:
                mint = balance.get("mint")
                amount = balance.get("uiTokenAmount", {}).get("uiAmount")
                if mint and amount is not None:
                    pre[mint] = float(amount)
            
            for balance in post_balances:
                mint = balance.get("mint")
                amount = balance.get("uiTokenAmount", {}).get("uiAmount")
                if mint and amount is not None:
                    post[mint] = float(amount)
            
            # Deltas berechnen
            all_mints = set(pre.keys()).union(post.keys())
            deltas = {}
            
            for mint in all_mints:
                pre_amount = pre.get(mint, 0)
                post_amount = post.get(mint, 0)
                delta = post_amount - pre_amount
                
                if abs(delta) > 0.000001:
                    deltas[mint] = delta
            
            if not deltas:
                return None
            
            # Kategorisiere: Currency vs Asset
            currency_deltas = {}
            asset_deltas = {}
            
            for mint, delta in deltas.items():
                if mint in CURRENCY_MINTS:
                    currency_deltas[mint] = delta
                else:
                    asset_deltas[mint] = delta
            
            # Trade identifizieren
            if currency_deltas and asset_deltas:
                # Currency <-> Asset Swap
                asset_mint = list(asset_deltas.keys())[0]
                asset_delta = asset_deltas[asset_mint]
                
                side = "BUY" if asset_delta > 0 else "SELL"
                amount = abs(asset_delta)
                
                return TradeEvent(
                    wallet=wallet,
                    token=asset_mint,
                    side=side,
                    amount=amount,
                    source="solana_polling",
                    raw_tx={"signature": signature, "meta": meta}
                )
            
            elif asset_deltas:
                # Asset <-> Asset Swap
                sorted_assets = sorted(
                    asset_deltas.items(),
                    key=lambda x: abs(x[1]),
                    reverse=True
                )
                token, delta = sorted_assets[0]
                
                side = "BUY" if delta > 0 else "SELL"
                amount = abs(delta)
                
                return TradeEvent(
                    wallet=wallet,
                    token=token,
                    side=side,
                    amount=amount,
                    source="solana_polling",
                    raw_tx={"signature": signature, "meta": meta}
                )
            
        except Exception as e:
            logger.error(f"[Polling] Error extracting trade: {e}", exc_info=True)
        
        return None


    async def emit_trade(self, trade_event: TradeEvent):
        """Emit Trade Event"""
        logger.info(f"[Polling] Trade detected: {trade_event}")
        
        if self.on_trade:
            if asyncio.iscoroutinefunction(self.on_trade):
                await self.on_trade(trade_event)
            else:
                self.on_trade(trade_event)


    def stop(self):
        """Stoppt Polling"""
        self.running = False
        logger.info("[Polling] Stopping...")
    
    def listen(self):
        """Dummy method for abstract base class (not used in async polling)"""
        raise NotImplementedError("Polling uses async connect() instead of listen()")
