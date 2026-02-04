import asyncio
import json
import time
import websockets

from observation.models import TradeEvent

# Stabiler kostenloser RPC
SOLANA_WS_URL = "wss://api.mainnet-beta.solana.com/"


class SolanaRPCSource:
    def __init__(self, wallets: list[str], callback):
        """
        wallets: Liste beobachteter Wallet-Adressen
        callback: observer.handle_event
        """
        self.wallets = wallets
        self.callback = callback

    async def listen(self):
        """
        Startet den WebSocket Listener (ASYNC!)
        """
        async with websockets.connect(
            SOLANA_WS_URL,
            open_timeout=20,
            close_timeout=5,
            ping_interval=20
        ) as ws:

            # Abos setzen
            for wallet in self.wallets:
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "id": wallet,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [wallet]},
                        {"commitment": "confirmed"}
                    ]
                }
                await ws.send(json.dumps(subscribe_msg))

            print("[RPC] Subscribed to wallets")

            # Nachrichten empfangen
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                self.handle_message(data)

    def handle_message(self, data: dict):
        """
        Minimaler Parser (V1)
        """
        if "params" not in data:
            return

        logs = data["params"]["result"]["value"].get("logs", [])

        # einfache Heuristik
        if not any("swap" in log.lower() for log in logs):
            return

        wallet = data["params"]["result"]["value"]["accounts"][0]

        event = TradeEvent(
            wallet=wallet,
            token="UNKNOWN",
            side="unknown",
            amount=0,
            timestamp=int(time.time()),
            source="rpc"
        )

        self.callback(event)
