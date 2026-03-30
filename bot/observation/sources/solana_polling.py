"""
Solana Polling Source - Alternative zu WebSocket Subscriptions
Fragt regelmäßig Wallet-Transaktionen ab und erkennt Trades
MIT CONNECTION HEALTH MONITORING
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
    3. Neue Transactions  Parse & Emit Trade Events
    4.  Connection Monitoring  Emergency Exit bei Netzwerkausfall
    """

    def __init__(
        self,
        rpc_http_url: str,
        wallets: list[str] = None,
        callback=None,
        poll_interval: int = 2,
        ignore_initial_txs: bool = True,
        fast_poll_interval: float = 0.5,
        connection_monitor=None,  #  Connection Health Monitor
    ):
        super().__init__()
        self.rpc_http_url = rpc_http_url
        self.wallets = list(wallets or [])
        self.poll_interval = poll_interval
        self.fast_poll_interval = fast_poll_interval
        self.seen_signatures: Set[str] = set()
        self.running = False
        self.ignore_initial_txs = ignore_initial_txs
        self.initial_load_done = False
        
        # Dynamisches Polling
        self.watch_wallets: Set[str] = set()
        self.is_fast_polling = False
        
        #  Connection Monitoring
        self.connection_monitor = connection_monitor
        
        print(f"[Polling] Normal interval: {poll_interval}s")
        print(f"[Polling] Fast interval: {fast_poll_interval}s (when position open)")
        print(f"[Polling] Watching {len(self.wallets)} wallets")
        if ignore_initial_txs:
            print(f"[Polling] Ignoring transactions before start time")
        if connection_monitor:
            print(f"[Polling]  Connection monitoring ENABLED")
        
        if callback:
            self.on_trade = callback


    async def connect(self):
        """Startet Polling Loop"""
        self.running = True
        logger.info(f"[Polling] Starting with {len(self.wallets)} wallets")
        
        #  Starte Connection Monitor
        if self.connection_monitor:
            await self.connection_monitor.start()
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            try:
                while self.running:
                    await self.poll_all_wallets()
                    
                    # Dynamisches Intervall basierend auf offenen Positionen
                    if self.is_fast_polling:
                        await asyncio.sleep(self.fast_poll_interval)
                    else:
                        await asyncio.sleep(self.poll_interval)
                    
            except asyncio.CancelledError:
                logger.info("[Polling] Cancelled, stopping...")
                self.running = False
                raise
            finally:
                #  Stoppe Connection Monitor
                if self.connection_monitor:
                    self.connection_monitor.stop()


    async def poll_all_wallets(self):
        """Fragt alle Wallets in Batches ab (verhindert Rate-Limiting)"""
        if self.is_fast_polling and self.watch_wallets:
            wallets = list(self.watch_wallets)
            batch_delay = 0.1
        else:
            wallets = list(self.wallets)
            batch_delay = 0.3

        # Batch-Groesse dynamisch: ~4 Batches pro Durchlauf, min 3 max 15
        batch_size = max(3, min(15, len(wallets) // 4 or 3))
        num_batches = (len(wallets) + batch_size - 1) // batch_size

        # Delay so berechnen dass wir unter RPC_MAX_RPS bleiben:
        # RPC_MAX_RPS Requests/s -> pro Batch max batch_size Requests
        # -> Pause = batch_size / RPC_MAX_RPS
        RPC_MAX_RPS = 8  # konservativer Wert fuer kostenlose RPCs
        min_delay   = batch_size / RPC_MAX_RPS
        batch_delay = max(batch_delay, min_delay)

        logger.debug(
            f"[Polling] {len(wallets)} wallets -> "
            f"{num_batches} Batches x {batch_size} @ {batch_delay:.2f}s delay"
            f" (~{batch_size/batch_delay:.1f} req/s)"
        )

        for i in range(0, len(wallets), batch_size):
            batch = wallets[i:i + batch_size]
            tasks = [self.poll_wallet(wallet) for wallet in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            if i + batch_size < len(wallets):
                await asyncio.sleep(batch_delay)

        if not self.initial_load_done:
            self.initial_load_done = True
            if self.ignore_initial_txs:
                logger.info("[Polling] Initial load complete - now watching for NEW transactions only")


    async def poll_wallet(self, wallet: str):
        """
        Fragt neueste Transactions einer Wallet ab
         MIT CONNECTION MONITORING
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    wallet,
                    {"limit": 5}
                ]
            }
            
            async with self.session.post(
                self.rpc_http_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json()
                
                #  SUCCESS  Melde an Monitor
                if self.connection_monitor:
                    self.connection_monitor.record_success()
                
                if "error" in data:
                    logger.error(f"[Polling] RPC Error for {wallet[:8]}...: {data['error']}")
                    return
                
                signatures = data.get("result", [])
                
                new_sigs = []
                for sig_info in signatures:
                    sig = sig_info.get("signature")
                    if sig and sig not in self.seen_signatures:
                        new_sigs.append(sig)
                        self.seen_signatures.add(sig)
                
                if not self.initial_load_done and self.ignore_initial_txs:
                    if new_sigs:
                        logger.debug(f"[Polling] {wallet[:8]}... marked {len(new_sigs)} initial transactions as seen")
                    return
                
                if new_sigs:
                    logger.info(f"[Polling] {wallet[:8]}... has {len(new_sigs)} new transactions")
                    
                    for sig in new_sigs:
                        await self.fetch_and_process_transaction(sig, wallet)
                        
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
            #  FAILURE  Melde an Monitor
            if self.connection_monitor:
                self.connection_monitor.record_failure()
            
            logger.error(f"[Polling] Error polling wallet {wallet[:8]}...: {e}")
        except Exception as e:
            logger.error(f"[Polling] Unexpected error polling wallet {wallet[:8]}...: {e}")


    async def fetch_and_process_transaction(self, signature: str, wallet: str):
        """Holt Transaction Details und verarbeitet sie"""
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
                
                trade_event = self.extract_trade(tx, wallet, signature)
                if trade_event:
                    await self.emit_trade(trade_event)
                    
        except Exception as e:
            logger.error(f"[Polling] Error fetching transaction {signature[:8]}...: {e}")


    def extract_trade(self, tx: dict, wallet: str, signature: str) -> Optional[TradeEvent]:
        """Extrahiert Trade Information aus Transaction"""
        try:
            meta = tx.get("meta", {})
            
            pre_balances = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])
            
            if not pre_balances and not post_balances:
                return None
            
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
            
            currency_deltas = {}
            asset_deltas = {}
            
            for mint, delta in deltas.items():
                if mint in CURRENCY_MINTS:
                    currency_deltas[mint] = delta
                else:
                    asset_deltas[mint] = delta
            
            if currency_deltas and asset_deltas:
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
        logger.debug(
            f"[Polling] Trade: {trade_event.wallet[:8]}... "
            f"{trade_event.side} {trade_event.amount:.2f} {trade_event.token[:8]}..."
        )
        
        if self.on_trade:
            if asyncio.iscoroutinefunction(self.on_trade):
                await self.on_trade(trade_event)
            else:
                self.on_trade(trade_event)


    def stop(self):
        """Stoppt Polling"""
        self.running = False
        logger.info("[Polling] Stopping...")
    
    def get_polling_status(self) -> dict:
        """Gibt aktuellen Polling Status zurück"""
        status = {
            'is_fast_polling': self.is_fast_polling,
            'watch_wallets': list(self.watch_wallets),
            'current_interval': self.fast_poll_interval if self.is_fast_polling else self.poll_interval
        }
        
        #  Connection Monitor Status
        if self.connection_monitor:
            status['connection'] = self.connection_monitor.get_status()
        
        return status
    
    def start_watching_wallets(self, wallets: list[str]):
        """Startet schnelles Polling für bestimmte Wallets"""
        self.watch_wallets = set(wallets)
        was_fast = self.is_fast_polling
        self.is_fast_polling = True
        
        if not was_fast:
            logger.info(f"[Polling]  FAST MODE activated for {len(wallets)} wallets (polling every {self.fast_poll_interval}s)")
    
    def stop_watching_wallets(self):
        """Stoppt schnelles Polling"""
        was_fast = self.is_fast_polling
        self.watch_wallets.clear()
        self.is_fast_polling = False
        
        if was_fast:
            logger.info(f"[Polling]  NORMAL MODE restored (polling every {self.poll_interval}s)")
    
    def listen(self):
        """Dummy method for abstract base class (not used in async polling)"""
        raise NotImplementedError("Polling uses async connect() instead of listen()")
