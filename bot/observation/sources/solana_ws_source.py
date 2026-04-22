"""
Solana Free Polling Source - Ersatz fuer Helius ohne Credit-Limits

Strategie: Mehrere kostenlose Public RPC Endpunkte rotieren.
Kein Helius, keine Credits, kein logsSubscribe (zu unzuverlaessig auf Public RPCs).

Stattdessen: getSignaturesForAddress + getTransaction - identisch zu SolanaPollingSource,
aber mit RPC-Rotation statt einem einzigen Helius-Endpunkt.

Vorteile:
- 0 Credits, kein Tageslimit
- Mehrere Endpunkte -> kein Single Point of Failure
- Identische Logik wie bewaehrtes Polling-System

Endpunkte (alle kostenlos, kein API-Key):
  https://api.mainnet-beta.solana.com   (Solana Labs)
  https://solana-api.projectserum.com   (Serum/Openbook)
  https://rpc.ankr.com/solana           (Ankr)
  https://solana-mainnet.g.alchemy.com/v2/demo  (Alchemy Demo)
"""

import asyncio
import json
import logging
import itertools
from typing import Optional, Dict, Set
import aiohttp

from observation.models import TradeEvent
from .base import TradeSource

logger = logging.getLogger(__name__)

CURRENCY_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

# Kostenlose Public RPC Endpunkte - kein API-Key noetig (Stand April 2026)
# Quellen: comparenodes.com, solana.com/docs
FREE_RPC_ENDPOINTS = [
    "https://api.mainnet-beta.solana.com",       # Solana Foundation (offiziell)
    "https://solana-rpc.publicnode.com",          # Allnodes (stabil, kein Key)
    "https://solana.drpc.org",                    # dRPC (kein Key fuer Basic)
    "https://solana.api.onfinality.io/public",   # OnFinality (kein Key)
    "https://solana-mainnet.gateway.tatum.io",   # Tatum (kein Key fuer Free)
    "https://public.rpc.solanavibestation.com",  # Solana Vibe Station
    "https://solana.rpc.subquery.network/public",# SubQuery Network
    "https://solana-api.projectserum.com",        # Serum/Openbook
    "https://solana.api.pocket.network",          # Pocket Network
    "https://rpc.ankr.com/solana",               # Ankr (kein Key fuer Public)
]

# Rate Limits pro Endpunkt (konservativ)
RPC_MAX_RPS = 5       # Requests pro Sekunde pro Endpunkt
POLL_INTERVAL = 3     # Sekunden zwischen Poll-Zyklen


class SolanaWebSocketSource(TradeSource):
    """
    Freies Polling-System mit RPC-Rotation.
    Gleiche Logik wie SolanaPollingSource, aber ohne Helius.
    Name bleibt SolanaWebSocketSource fuer Kompatibilitaet mit wallet_analysis.py.
    """

    def __init__(
        self,
        ws_url: str,         # wird nicht verwendet, aber Interface-kompatibel
        http_url: str,       # wird als erster Endpunkt genutzt (falls kein Free RPC)
        wallets: list = None,
        callback=None,
        ignore_initial_txs: bool = True,
        connection_monitor=None,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 0,
    ):
        super().__init__()

        self.wallets             = list(wallets or [])
        self.ignore_initial_txs  = ignore_initial_txs
        self.connection_monitor  = connection_monitor
        self.reconnect_delay     = reconnect_delay
        self.poll_interval       = POLL_INTERVAL

        # RPC Endpunkte: Free RPCs bevorzugen, http_url als Fallback
        self.rpc_endpoints = list(FREE_RPC_ENDPOINTS)
        if http_url not in self.rpc_endpoints:
            self.rpc_endpoints.append(http_url)

        # Round-Robin Iterator ueber Endpunkte
        self._rpc_cycle = itertools.cycle(self.rpc_endpoints)
        self._endpoint_failures: Dict[str, int] = {ep: 0 for ep in self.rpc_endpoints}

        # Kompatibilitaet mit SolanaPollingSource Interface
        self.rpc_http_url    = self.rpc_endpoints[0]  # fuer _check_for_missed_sells
        self.is_fast_polling = False
        self.watch_wallets:  Set[str] = set()

        self.running              = False
        self.connected            = False
        self.initial_load_done    = False
        self.seen_signatures:     Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None

        if callback:
            self.on_trade = callback

        print(f"[FreeRPC] Polling Source initialisiert (ohne Helius, ohne Credits)")
        print(f"[FreeRPC] Endpunkte ({len(self.rpc_endpoints)}x rotierend):")
        for ep in self.rpc_endpoints:
            print(f"[FreeRPC]   {ep}")
        print(f"[FreeRPC] Poll-Intervall: {POLL_INTERVAL}s | Max {RPC_MAX_RPS} req/s pro Endpunkt")
        print(f"[FreeRPC] Watching {len(self.wallets)} wallets")
        if connection_monitor:
            print(f"[FreeRPC] Connection monitoring ENABLED")

    # ------------------------------------------------------------------
    # PUBLIC API (identisch zu SolanaPollingSource)
    # ------------------------------------------------------------------

    async def connect(self):
        """Startet Polling-Loop mit RPC-Rotation."""
        self.running = True

        if self.connection_monitor:
            await self.connection_monitor.start()

        async with aiohttp.ClientSession() as session:
            self._session = session

            try:
                while self.running:
                    await self._poll_all_wallets()

                    interval = (
                        self.poll_interval / 2
                        if self.is_fast_polling and self.watch_wallets
                        else self.poll_interval
                    )
                    await asyncio.sleep(interval)

            except asyncio.CancelledError:
                self.running = False
                raise
            finally:
                if self.connection_monitor:
                    self.connection_monitor.stop()

    def stop(self):
        self.running = False
        print(f"[FreeRPC] Stopping...")

    def get_polling_status(self) -> dict:
        status = {
            'is_fast_polling':  self.is_fast_polling,
            'watch_wallets':    list(self.watch_wallets),
            'current_interval': self.poll_interval,
            'endpoints':        self.rpc_endpoints,
        }
        if self.connection_monitor:
            status['connection'] = self.connection_monitor.get_status()
        return status

    def start_watching_wallets(self, wallets: list):
        self.watch_wallets   = set(wallets)
        self.is_fast_polling = True
        print(f"[FreeRPC] FAST MODE fuer {len(wallets)} Wallets")

    def stop_watching_wallets(self):
        self.watch_wallets.clear()
        self.is_fast_polling = False
        print(f"[FreeRPC] NORMAL MODE wiederhergestellt")

    def listen(self):
        raise NotImplementedError("FreeRPC Source nutzt async connect()")

    # ------------------------------------------------------------------
    # POLLING LOOP
    # ------------------------------------------------------------------

    async def _poll_all_wallets(self):
        """Fragt alle Wallets sequenziell in Batches ab."""
        if self.is_fast_polling and self.watch_wallets:
            wallets = list(self.watch_wallets)
        else:
            wallets = list(self.wallets)

        batch_size  = max(3, min(10, len(wallets) // 4 or 3))
        min_delay   = batch_size / RPC_MAX_RPS
        batch_delay = max(0.3, min_delay)

        for i in range(0, len(wallets), batch_size):
            batch = wallets[i:i + batch_size]
            # Sequenziell statt parallel - verhindert Race Conditions bei seen_signatures
            for wallet in batch:
                await self._poll_wallet(wallet)
            if i + batch_size < len(wallets):
                await asyncio.sleep(batch_delay)

        if not self.initial_load_done:
            self.initial_load_done = True
            if self.ignore_initial_txs:
                print(f"[FreeRPC] Initial load abgeschlossen - beobachte jetzt neue Transaktionen")

    def _next_endpoint(self) -> str:
        """Gibt naechsten Endpunkt aus dem Round-Robin zurück, ueberspringt kaputte."""
        for _ in range(len(self.rpc_endpoints)):
            ep = next(self._rpc_cycle)
            if self._endpoint_failures.get(ep, 0) < 5:
                return ep
        # Alle kaputt -> Reset und ersten nehmen
        self._endpoint_failures = {ep: 0 for ep in self.rpc_endpoints}
        return self.rpc_endpoints[0]

    async def _poll_wallet(self, wallet: str):
        """Fragt neue Transaktionen einer Wallet ab."""
        endpoint = self._next_endpoint()
        try:
            payload = {
                "jsonrpc": "2.0",
                "id":      1,
                "method":  "getSignaturesForAddress",
                "params":  [wallet, {"limit": 5}]
            }
            async with self._session.post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json(content_type=None)

            # Nur globalen Monitor informieren wenn der primaere Endpunkt antwortet
            if self.connection_monitor and endpoint == self.rpc_endpoints[0]:
                self.connection_monitor.record_success()

            self._endpoint_failures[endpoint] = 0

            # Sicherheitscheck: manche Endpunkte liefern HTML/String statt JSON-Objekt
            if not isinstance(data, dict):
                logger.debug(f"[FreeRPC] {endpoint[:30]}... liefert kein JSON-Objekt: {str(data)[:60]}")
                return

            if "error" in data:
                logger.debug(f"[FreeRPC] RPC Error {wallet[:8]}...: {data['error']}")
                return

            signatures = data.get("result", [])
            if not isinstance(signatures, list):
                logger.debug(f"[FreeRPC] {endpoint[:30]}... result ist keine Liste")
                return
            new_sigs   = []

            for sig_info in signatures:
                sig = sig_info.get("signature")
                # Atomarer Check+Add verhindert Duplikate bei parallelen Tasks
                if sig and sig not in self.seen_signatures:
                    self.seen_signatures.add(sig)
                    new_sigs.append(sig)

            # Initial-Load: Signaturen merken aber nicht verarbeiten
            if not self.initial_load_done and self.ignore_initial_txs:
                return

            if new_sigs:
                print(f"[FreeRPC] {wallet[:8]}... hat {len(new_sigs)} neue TX(s)")
                for sig in new_sigs:
                    await self._fetch_and_process(sig, wallet, endpoint)

        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
            # Endpunkt-Fehler zaehlen aber NICHT den globalen Connection Monitor triggern
            # (einzelner kaputte Endpunkt != Netzwerkausfall)
            self._endpoint_failures[endpoint] = self._endpoint_failures.get(endpoint, 0) + 1
            fails = self._endpoint_failures[endpoint]
            if fails <= 2:
                logger.warning(f"[FreeRPC] {endpoint[:35]}... Fehler: {type(e).__name__} ({fails}/5)")
            elif fails == 5:
                print(f"[FreeRPC] {endpoint[:35]}... wird temporaer uebersprungen (5x Fehler)")
        except Exception as e:
            logger.error(f"[FreeRPC] Unerwarteter Fehler bei {wallet[:8]}...: {e}", exc_info=True)

    async def _fetch_and_process(self, signature: str, wallet: str, endpoint: str):
        """Holt TX Details und extrahiert Trade - identisch zu SolanaPollingSource."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id":      1,
                "method":  "getTransaction",
                "params":  [
                    signature,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
                ]
            }
            async with self._session.post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json(content_type=None)

            if not isinstance(data, dict):
                logger.debug(f"[FreeRPC] getTransaction {signature[:8]}... kein JSON-Objekt")
                return

            if "error" in data:
                logger.debug(f"[FreeRPC] getTransaction Fehler {signature[:8]}...: {data['error']}")
                return

            tx = data.get("result")
            if not tx:
                return

            trade_event = self.extract_trade(tx, wallet, signature)
            if trade_event:
                await self._emit_trade(trade_event)

        except Exception as e:
            logger.error(f"[FreeRPC] _fetch_and_process Fehler: {e}", exc_info=True)

    def extract_trade(self, tx: dict, wallet: str, signature: str) -> Optional[TradeEvent]:
        """Identische Logik wie SolanaPollingSource.extract_trade()"""
        try:
            meta          = tx.get("meta", {})
            pre_balances  = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])

            if not pre_balances and not post_balances:
                return None

            pre  = {}
            post = {}
            for b in pre_balances:
                mint   = b.get("mint")
                amount = b.get("uiTokenAmount", {}).get("uiAmount")
                if mint and amount is not None:
                    pre[mint] = float(amount)
            for b in post_balances:
                mint   = b.get("mint")
                amount = b.get("uiTokenAmount", {}).get("uiAmount")
                if mint and amount is not None:
                    post[mint] = float(amount)

            deltas = {}
            for mint in set(pre) | set(post):
                delta = post.get(mint, 0) - pre.get(mint, 0)
                if abs(delta) > 0.000001:
                    deltas[mint] = delta

            if not deltas:
                return None

            currency_deltas = {m: d for m, d in deltas.items() if m in CURRENCY_MINTS}
            asset_deltas    = {m: d for m, d in deltas.items() if m not in CURRENCY_MINTS}

            if currency_deltas and asset_deltas:
                asset_mint  = list(asset_deltas.keys())[0]
                asset_delta = asset_deltas[asset_mint]
                return TradeEvent(
                    wallet=wallet, token=asset_mint,
                    side="BUY" if asset_delta > 0 else "SELL",
                    amount=abs(asset_delta), source="free_rpc_polling",
                    raw_tx={"signature": signature, "meta": meta}
                )
            elif asset_deltas:
                token, delta = max(asset_deltas.items(), key=lambda x: abs(x[1]))
                return TradeEvent(
                    wallet=wallet, token=token,
                    side="BUY" if delta > 0 else "SELL",
                    amount=abs(delta), source="free_rpc_polling",
                    raw_tx={"signature": signature, "meta": meta}
                )

        except Exception as e:
            logger.error(f"[FreeRPC] extract_trade Fehler: {e}", exc_info=True)

        return None

    async def _emit_trade(self, trade_event: TradeEvent):
        logger.info(
            f" [analysis] {trade_event.wallet[:8]}... "
            f"{trade_event.side:4} {trade_event.amount:>12.2f} {trade_event.token[:8]}..."
        )
        if self.on_trade:
            if asyncio.iscoroutinefunction(self.on_trade):
                await self.on_trade(trade_event)
            else:
                self.on_trade(trade_event)
