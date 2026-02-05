import asyncio
import json
import time
import websockets
import aiohttp

from observation.sources.base import TradeSource
from observation.events import TradeEvent


SOLANA_WS_URL = "wss://api.mainnet-beta.solana.com/"
SOLANA_HTTP_URL = "https://api.mainnet-beta.solana.com"


class SolanaRPCSource(TradeSource):
    """
    Beobachtet Solana Wallets über RPC WebSocket + getTransaction
    """

    def __init__(self, wallets: list[str], callback):
        self.wallets = set(wallets)
        self.callback = callback

    async def listen(self):
        """
        Haupt-Loop:
        - WebSocket verbinden
        - Logs abonnieren
        - Signaturen empfangen
        - Transactions auflösen
        """
        async with websockets.connect(
            SOLANA_WS_URL,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:

            await self.subscribe(ws)
            print("[RPC] Subscribed to wallets")

            while True:
                try:
                    raw_msg = await ws.recv()
                    data = json.loads(raw_msg)
                    await self.handle_message(data)

                except asyncio.CancelledError:
                    raise

                except Exception as e:
                    print(f"[RPC] Error: {e}")

    async def subscribe(self, ws):
        """
        Abonniert Logs (alle Programme).
        Wallet-Filter erfolgt später beim Parsen.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": list(self.wallets)},
                {"commitment": "confirmed"}
            ]
        }

        await ws.send(json.dumps(payload))

    async def handle_message(self, data: dict):
        """
        Verarbeitet eingehende Log-Events
        """
        if "params" not in data:
            return

        result = data["params"]["result"]
        value = result.get("value", {})
        logs = value.get("logs", [])

        # einfache Swap-Heuristik (V1)
        if not any("swap" in log.lower() for log in logs):
            return

        signature = result.get("signature")
        if not signature:
            return

        print(f"[RPC] Swap detected | signature={signature}")

        tx = await self.fetch_transaction(signature)
        if not tx:
            return

        wallet = self.extract_wallet(tx)
        if not wallet:
            return

        event = TradeEvent(
            wallet=wallet,
            token="UNKNOWN",
            side="UNKNOWN",
            amount=0,
            timestamp=int(time.time()),
            source="rpc"
        )

        self.callback(event)

    async def resolve_transaction(self, signature: str):
        
        # 1. Holen der Transaction
        tx = await self.fetch_transaction(signature)
        if not tx:
            return

        # 2. Wallet bestimmen
        wallet = self.extract_wallet(tx)
        if not wallet:
            return

        # 3. Event erzeugen
        event = TradeEvent(
            wallet=wallet,
            token="UNKNOWN",
            side="UNKNOWN",
            amount=0,
            timestamp=int(time.time()),
            source="rpc"
        )

        await self.callback(event)


    async def fetch_transaction(self, signature: str) -> dict | None:
        """
        Holt eine vollständige Transaction via HTTP RPC
        """
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

        async with aiohttp.ClientSession() as session:
            async with session.post(SOLANA_HTTP_URL, json=payload) as resp:
                data = await resp.json()
                return data.get("result")

    def extract_wallet(self, tx: dict) -> str | None:
        """
        Sucht die beobachtete Wallet in den AccountKeys
        """
        try:
            accounts = tx["transaction"]["message"]["accountKeys"]
        except KeyError:
            return None

        for acc in accounts:
            if isinstance(acc, dict):
                pubkey = acc.get("pubkey")
            else:
                pubkey = acc

            if pubkey in self.wallets:
                return pubkey

        return None
