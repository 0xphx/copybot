import asyncio
import json
import logging
from typing import Optional, Dict, Any

import websockets

from observation.models import TradeEvent
from .base import TradeSource

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class SolanaRPCSource(TradeSource):

    def __init__(self, rpc_ws_url: str = "wss://api.mainnet-beta.solana.com", wallets: list[str] = None, callback=None):
        super().__init__()
        self.rpc_ws_url = rpc_ws_url
        self.wallets = set(wallets or [])
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.sub_id: Optional[int] = None

        # Debug-Ausgabe
        print("[Debug] Watching wallets:")
        for w in self.wallets:
            print("-", w)

        # Callback an den Observer binden
        if callback:
            self.on_trade = callback


    async def connect(self):
        """Stabile Verbindung mit Retry & Keepalive"""
        while True:
            try:
                async with websockets.connect(self.rpc_ws_url, ping_interval=20) as ws:
                    self.ws = ws
                    await self.subscribe_logs()
                    logger.info("WebSocket connected, listening for events...")
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


    async def subscribe_logs(self):
        """Abonniert Logs für alle Wallets"""
        if not self.ws:
            return
        params = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": list(self.wallets)},
                {"commitment": "confirmed"}
            ],
        }
        await self.ws.send(json.dumps(params))
        response = await self.ws.recv()
        data = json.loads(response)
        self.sub_id = data.get("result")
        logger.info(f"Subscribed to logs with subscription ID: {self.sub_id}")

    async def listen(self):
        """Endloser Listener für eingehende Nachrichten"""
        if not self.ws:
            return
        try:
            async for message in self.ws:
                await self.handle_message(message)
        except asyncio.CancelledError:
            logger.info("Listener cancelled during message iteration")
            raise


    async def handle_message(self, message: str):
        """Verarbeitet einzelne Log-Nachrichten"""
        try:
            data = json.loads(message)
            if "params" not in data:
                return
            tx = data["params"]["result"]["transaction"]
            meta = data["params"]["result"].get("meta", {})
            wallet = self.extract_wallet(tx)
            if not wallet:
                return

            trade_event = self.normalize_trade(tx, meta, wallet)
            if trade_event:
                self.emit_trade(trade_event)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def extract_wallet(self, tx: dict) -> Optional[str]:
        """Ermittelt, welche Wallet in der Transaktion beteiligt ist"""
        try:
            for key in tx["message"]["accountKeys"]:
                if key in self.wallets:
                    return key
        except KeyError:
            return None
        return None

    def normalize_trade(self, tx: dict, meta: dict, wallet: str) -> Optional[TradeEvent]:
        """Berechnet Side, Token und Amount aus pre/post Token Balances"""
        pre = {b["mint"]: int(b["uiTokenAmount"]["amount"]) for b in meta.get("preTokenBalances", [])}
        post = {b["mint"]: int(b["uiTokenAmount"]["amount"]) for b in meta.get("postTokenBalances", [])}

        # Berechne Deltas
        deltas = {}
        for mint in set(pre.keys()).union(post.keys()):
            delta = post.get(mint, 0) - pre.get(mint, 0)
            if delta != 0:
                deltas[mint] = delta

        if not deltas:
            return None

        # Nimm das erste Token-Delta als TradeEvent
        for mint, delta in deltas.items():
            side = "BUY" if delta > 0 else "SELL"
            # Annahme: 6 decimals, evtl anpassen je Token
            amount = abs(delta) / (10 ** 6)
            return TradeEvent(
                wallet=wallet,
                token=mint,
                side=side,
                amount=amount,
                raw_tx=tx
            )

    def emit_trade(self, trade_event: TradeEvent):
        """Emit TradeEvent an Observer"""
        logger.info(f"Trade detected: {trade_event}")
        self.on_trade(trade_event)
