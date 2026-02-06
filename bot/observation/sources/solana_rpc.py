import asyncio
import json
import logging
from typing import Optional, Dict, Any, List, Tuple

import websockets

from observation.models import TradeEvent
from .base import TradeSource

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)  # Changed back to INFO for cleaner output


# Bekannte "Währungs"-Tokens (SOL, USDC, USDT)
CURRENCY_MINTS = {
    "So11111111111111111111111111111111111111112",  # Wrapped SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}


class SolanaRPCSource(TradeSource):

    def __init__(
        self,
        rpc_ws_url: str = "wss://api.mainnet-beta.solana.com",
        wallets: list[str] = None,
        callback=None,
        mode: str = "wallets",
    ):
        super().__init__()
        self.rpc_ws_url = rpc_ws_url
        self.wallets = set(wallets or [])
        self.mode = mode
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.sub_ids: List[Tuple[str, int]] = []  # List of (wallet, sub_id) tuples

        print(f"[Debug] SolanaRPCSource mode = {self.mode}")
        print("[Debug] Watching wallets:")
        for w in self.wallets:
            print("-", w)

        if callback:
            self.on_trade = callback


    async def connect(self):
        """Stabile Verbindung mit Retry & Keepalive"""
        while True:
            try:
                async with websockets.connect(
                    self.rpc_ws_url, 
                    ping_interval=20,
                    open_timeout=10,
                    close_timeout=10
                ) as ws:
                    self.ws = ws
                    await self.subscribe_accounts()
                    logger.info("WebSocket connected, listening for account changes...")
                    
                    try:
                        await self.listen()
                    except asyncio.CancelledError:
                        logger.info("WebSocket listener cancelled. Closing connection...")
                        break

            except asyncio.CancelledError:
                logger.info("WebSocket connect cancelled. Exiting...")
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}, reconnecting in 3s...")
                await asyncio.sleep(3)


    async def subscribe_accounts(self):
        """Subscribe to account changes for each wallet"""
        if not self.ws:
            return

        # SCAN_ALL MODE
        if self.mode == "all":
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": ["all", {"commitment": "confirmed"}],
            }
            await self.ws.send(json.dumps(payload))
            response = await self.ws.recv()
            data = json.loads(response)
            sub_id = data.get("result")
            logger.info(f"[WS] Subscribed to ALL logs, sub_id={sub_id}")
            return

        # WALLET MODE - Subscribe each wallet individually
        if not self.wallets:
            logger.warning("[WS] Wallet mode active but wallet list is empty")
            return

        self.sub_ids = []
        for idx, wallet in enumerate(self.wallets, start=1):
            payload = {
                "jsonrpc": "2.0",
                "id": idx,
                "method": "accountSubscribe",
                "params": [
                    wallet,
                    {"encoding": "jsonParsed", "commitment": "confirmed"}
                ],
            }
            
            await self.ws.send(json.dumps(payload))
            response = await self.ws.recv()
            data = json.loads(response)
            
            sub_id = data.get("result")
            if sub_id:
                self.sub_ids.append((wallet, sub_id))
                logger.info(f"[WS] Subscribed wallet {wallet[:8]}..., sub_id={sub_id}")
            else:
                error = data.get("error", {})
                logger.error(f"[WS] Failed to subscribe wallet {wallet[:8]}...: {error}")
        
        logger.info(f"[WS] Successfully subscribed to {len(self.sub_ids)}/{len(self.wallets)} wallets")


    async def listen(self):
        """Endloser Listener für eingehende Nachrichten"""
        if not self.ws:
            return
        try:
            async for message in self.ws:
                await self.handle_account_update(message)
        except asyncio.CancelledError:
            logger.info("Listener cancelled during message iteration")
            raise


    async def handle_account_update(self, message: str):
        """Handle accountSubscribe notifications"""
        try:
            data = json.loads(message)
            
            # Skip subscription confirmations
            if "params" not in data:
                return
            
            # Get notification
            params = data.get("params", {})
            result = params.get("result")
            
            if not result:
                return
            
            # AccountSubscribe sends account state changes
            # We log these but note: this won't catch all trades immediately
            # For real-time trade detection, we'd need transactionSubscribe or logsSubscribe
            
            logger.info(f"[Account Update] Received account change notification")
            logger.debug(f"[Account Update] Data: {json.dumps(result, indent=2)}")
            
            # Note: accountSubscribe gives us account state but not transaction details
            # This is a limitation - we see balance changes but not the actual trades
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON: {e}")
        except Exception as e:
            logger.error(f"Error handling account update: {e}", exc_info=True)


    async def emit_trade(self, trade_event: TradeEvent):
        """Emit TradeEvent an Observer"""
        logger.info(f"Trade detected: {trade_event}")
        
        if self.on_trade:
            if asyncio.iscoroutinefunction(self.on_trade):
                await self.on_trade(trade_event)
            else:
                self.on_trade(trade_event)
