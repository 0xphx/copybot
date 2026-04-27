"""
Solana Parallel-Key Source

Strategie: N Keys laufen parallel, jeder Key pollt eine eigene Wallet-Gruppe.
Kein Wallet wird doppelt gepollt -> kein Credit-Verschwendung.

Beim Start waehlst du wie viele Keys parallel laufen sollen.
Die Wallets werden gleichmaessig aufgeteilt.

Faellt ein Key aus (erschoepft / Fehler), werden seine Wallets
automatisch auf die verbleibenden Keys umverteilt.
Sind alle Keys erschoepft, greift der Public-RPC-Fallback.

Neue Keys: https://dev.helius.xyz/dashboard
Keys eintragen in: config/network.py -> HELIUS_API_KEYS
"""

import asyncio
import itertools
import logging
from typing import Dict, List, Optional, Set

import aiohttp

from config.network import HELIUS_API_KEYS, HELIUS_HTTP_ENDPOINTS, PUBLIC_FALLBACK_ENDPOINTS
from observation.models import TradeEvent
from .base import TradeSource

logger = logging.getLogger(__name__)

CURRENCY_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

CREDITS_PER_MONTH = 1_000_000
POLL_INTERVAL     = 3       # Sekunden zwischen Poll-Zyklen pro Key-Task
RPC_MAX_RPS       = 8       # Max Requests/Sekunde pro Helius-Key
PUBLIC_MAX_RPS    = 5


# ──────────────────────────────────────────────────────────────────────────────
# Key-Slot (identisch zu solana_ws_source.py, eigenstaendig um Abhaengigkeiten zu vermeiden)
# ──────────────────────────────────────────────────────────────────────────────

class _KeySlot:
    """Verwaltet einen einzelnen Helius API Key mit Credit-Tracking."""

    def __init__(self, key: str, url: str):
        self.key               = key
        self.url               = url
        self.label             = f"Helius ...{key[-6:]}"
        self.credits           = 0
        self.credits_remaining: Optional[int] = None
        self.errors            = 0
        self.exhausted         = False
        self._month            = self._current_month()
        self.wallets:  List[str] = []   # aktuell zugewiesene Wallets

    @staticmethod
    def _current_month():
        from datetime import date
        d = date.today()
        return (d.year, d.month)

    def _reset_if_new_month(self):
        current = self._current_month()
        if current != self._month:
            self._month    = current
            self.credits   = 0
            self.exhausted = False
            self.errors    = 0
            print(f"[Parallel] {self.label}: Neuer Monat - Credits zurueckgesetzt")

    def record_success(self, cost: int = 1, headers=None):
        self._reset_if_new_month()
        self.credits += cost
        self.errors   = 0
        if headers:
            for hdr in ('x-ratelimit-remaining-month', 'x-credits-remaining',
                        'ratelimit-remaining', 'x-ratelimit-remaining'):
                val = headers.get(hdr)
                if val is not None:
                    try:
                        self.credits_remaining = int(val)
                        self.credits = CREDITS_PER_MONTH - self.credits_remaining
                    except (ValueError, TypeError):
                        pass
                    break
        if self.credits >= CREDITS_PER_MONTH:
            if not self.exhausted:
                remaining = max(0, self.credits_remaining or 0)
                print(f"[Parallel] {self.label}: Monatslimit erreicht "
                      f"({self.credits:,}/{CREDITS_PER_MONTH:,}, {remaining:,} verbleibend)")
            self.exhausted = True
        elif self.credits % 100_000 == 0 and self.credits > 0:
            remaining = (self.credits_remaining if self.credits_remaining is not None
                         else CREDITS_PER_MONTH - self.credits)
            print(f"[Parallel] {self.label}: {self.credits:,}/{CREDITS_PER_MONTH:,} Credits "
                  f"({remaining:,} verbleibend)")

    def record_error(self, is_exhausted_error: bool = False):
        self._reset_if_new_month()
        self.errors += 1
        if is_exhausted_error:
            self.exhausted = True
            print(f"[Parallel] {self.label}: Limit erschoepft")

    def is_available(self) -> bool:
        self._reset_if_new_month()
        return not self.exhausted and self.errors < 5

    def status_str(self) -> str:
        state = "ERSCHOEPFT" if self.exhausted else ("FEHLER" if self.errors >= 5 else "OK")
        wallets_n = len(self.wallets)
        if self.credits_remaining is not None:
            pct = self.credits_remaining / CREDITS_PER_MONTH * 100
            return (f"{self.label}: {self.credits_remaining:,} verbleibend "
                    f"({pct:.0f}%)  [{state}]  {wallets_n} Wallets")
        else:
            remaining = max(0, CREDITS_PER_MONTH - self.credits)
            pct       = remaining / CREDITS_PER_MONTH * 100
            return (f"{self.label}: ~{remaining:,} verbleibend "
                    f"({pct:.0f}%)  [{state}]  {wallets_n} Wallets  (geschaetzt)")


# ──────────────────────────────────────────────────────────────────────────────
# Parallel Source
# ──────────────────────────────────────────────────────────────────────────────

class SolanaParallelSource(TradeSource):
    """
    Jeder Key laeuft als eigener asyncio-Task und pollt seine Wallet-Gruppe.
    Faellt ein Key aus, werden seine Wallets auf aktive Keys umverteilt.
    """

    def __init__(
        self,
        wallets:            list,
        callback,
        num_parallel_keys:  int,
        connection_monitor=None,
        ignore_initial_txs: bool = True,
    ):
        super().__init__()

        self.all_wallets        = list(wallets)
        self.on_trade           = callback
        self.num_parallel_keys  = num_parallel_keys
        self.connection_monitor = connection_monitor
        self.ignore_initial_txs = ignore_initial_txs

        self.running            = False
        self.is_fast_polling    = False
        self.watch_wallets: Set[str] = set()
        self.seen_signatures: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None
        self._rebalance_lock    = asyncio.Lock()

        # Public Fallback
        self._public_endpoints  = list(PUBLIC_FALLBACK_ENDPOINTS)
        self._public_failures:  Dict[str, int] = {ep: 0 for ep in self._public_endpoints}
        self._public_cycle      = itertools.cycle(self._public_endpoints)
        self._using_fallback    = False
        self._fallback_wallets: List[str] = []  # Wallets die auf Public laufen

        # Kompatibilitaet mit wallet_analysis.py
        self.rpc_http_url = HELIUS_HTTP_ENDPOINTS[0] if HELIUS_HTTP_ENDPOINTS else PUBLIC_FALLBACK_ENDPOINTS[0]

        # Verfuegbare Keys auf num_parallel_keys begrenzen
        available_keys = [(k, u) for k, u in zip(HELIUS_API_KEYS, HELIUS_HTTP_ENDPOINTS)]
        if num_parallel_keys > len(available_keys):
            print(f"[Parallel] Nur {len(available_keys)} Keys verfuegbar, "
                  f"nutze alle statt {num_parallel_keys}.")
            num_parallel_keys = len(available_keys)
        self.num_parallel_keys = num_parallel_keys

        self._key_slots: List[_KeySlot] = [
            _KeySlot(key, url)
            for key, url in available_keys[:num_parallel_keys]
        ]

        # Initiale Wallet-Aufteilung
        self._distribute_wallets()
        self._print_startup()

    # ──────────────────────────────────────────────────────────────────
    # Wallet-Verteilung
    # ──────────────────────────────────────────────────────────────────

    def _distribute_wallets(self):
        """Verteilt alle Wallets gleichmaessig auf verfuegbare Keys."""
        active_slots = [s for s in self._key_slots if s.is_available()]
        if not active_slots:
            self._fallback_wallets = list(self.all_wallets)
            return

        # Alle Wallet-Listen leeren
        for slot in self._key_slots:
            slot.wallets = []
        self._fallback_wallets = []

        # Round-Robin Verteilung
        for i, wallet in enumerate(self.all_wallets):
            active_slots[i % len(active_slots)].wallets.append(wallet)

    async def _rebalance(self):
        """
        Wird aufgerufen wenn ein Key erschoepft ist.
        Verteilt seine Wallets auf verbleibende aktive Keys.
        """
        async with self._rebalance_lock:
            active_slots    = [s for s in self._key_slots if s.is_available()]
            inactive_slots  = [s for s in self._key_slots if not s.is_available()]

            if not inactive_slots:
                return  # Nichts zu tun

            # Verwaiste Wallets einsammeln
            orphaned = []
            for slot in inactive_slots:
                orphaned.extend(slot.wallets)
                slot.wallets = []

            if not orphaned:
                return

            print(f"[Parallel] Rebalancing: {len(orphaned)} Wallets von "
                  f"{len(inactive_slots)} ausgefallenen Key(s) umverteilen...")

            if not active_slots:
                # Alle Keys erschoepft -> Public Fallback
                if not self._using_fallback:
                    self._using_fallback = True
                    print("[Parallel] Alle Keys erschoepft - wechsle auf Public Fallback")
                self._fallback_wallets.extend(orphaned)
                return

            # Gleichmaessig auf aktive Keys verteilen
            for i, wallet in enumerate(orphaned):
                active_slots[i % len(active_slots)].wallets.append(wallet)

            print(f"[Parallel] Rebalancing abgeschlossen:")
            for slot in active_slots:
                print(f"  {slot.label}: {len(slot.wallets)} Wallets")

    # ──────────────────────────────────────────────────────────────────
    # Startup
    # ──────────────────────────────────────────────────────────────────

    def _print_startup(self):
        total_credits = self.num_parallel_keys * CREDITS_PER_MONTH
        print()
        print(f"[Parallel] Parallel-Key Source gestartet")
        print(f"[Parallel] {self.num_parallel_keys} Keys parallel  |  "
              f"{total_credits:,} Credits/Monat gesamt")
        print(f"[Parallel] {len(self.all_wallets)} Wallets aufgeteilt:")
        for slot in self._key_slots:
            print(f"  {slot.label}: {len(slot.wallets)} Wallets")
        if self._public_endpoints:
            print(f"[Parallel] Fallback: {len(self._public_endpoints)} Public RPC(s)")
        print(f"[Parallel] Poll-Intervall: {POLL_INTERVAL}s pro Key-Task")
        print()

    # ──────────────────────────────────────────────────────────────────
    # Haupt-Loop
    # ──────────────────────────────────────────────────────────────────

    async def connect(self):
        self.running = True
        if self.connection_monitor:
            await self.connection_monitor.start()

        async with aiohttp.ClientSession() as session:
            self._session = session
            try:
                # Einen Task pro Key + optionaler Fallback-Task
                tasks = [
                    asyncio.create_task(self._key_task(slot))
                    for slot in self._key_slots
                ]
                tasks.append(asyncio.create_task(self._fallback_task()))
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                self.running = False
                raise
            finally:
                if self.connection_monitor:
                    self.connection_monitor.stop()
                self._print_credit_summary()

    def stop(self):
        self.running = False
        print("[Parallel] Stopping...")

    def listen(self):
        raise NotImplementedError("ParallelSource nutzt async connect()")

    # ──────────────────────────────────────────────────────────────────
    # Key-Task (laeuft pro Key parallel)
    # ──────────────────────────────────────────────────────────────────

    async def _key_task(self, slot: _KeySlot):
        """Eigener Poll-Loop fuer einen Key. Pollt nur seine Wallet-Gruppe."""
        initial_done = False
        print(f"[Parallel] Task gestartet: {slot.label} ({len(slot.wallets)} Wallets)")

        while self.running:
            if not slot.is_available():
                # Key erschoepft -> Rebalancing ausloesen und Task beenden
                await self._rebalance()
                print(f"[Parallel] Task beendet: {slot.label} (erschoepft)")
                return

            wallets = list(slot.wallets)  # Snapshot, falls Rebalancing laeuft
            if not wallets:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Wallets in Batches aufteilen
            batch_size  = max(3, min(10, len(wallets) // 4 or 3))
            batch_delay = max(0.3, batch_size / RPC_MAX_RPS)

            for i in range(0, len(wallets), batch_size):
                if not self.running:
                    return
                for wallet in wallets[i:i + batch_size]:
                    await self._poll_wallet(wallet, slot)
                if i + batch_size < len(wallets):
                    await asyncio.sleep(batch_delay)

            if not initial_done and self.ignore_initial_txs:
                initial_done = True
                print(f"[Parallel] {slot.label}: Initial load abgeschlossen")

            await asyncio.sleep(POLL_INTERVAL)

    # ──────────────────────────────────────────────────────────────────
    # Fallback-Task (Public RPC fuer erschoepfte Keys)
    # ──────────────────────────────────────────────────────────────────

    async def _fallback_task(self):
        """Pollt Wallets die keinem Helius-Key mehr zugewiesen sind."""
        while self.running:
            wallets = list(self._fallback_wallets)
            if not wallets:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            batch_size  = max(3, min(8, len(wallets) // 4 or 3))
            batch_delay = max(0.4, batch_size / PUBLIC_MAX_RPS)

            for i in range(0, len(wallets), batch_size):
                if not self.running:
                    return
                for wallet in wallets[i:i + batch_size]:
                    await self._poll_wallet_public(wallet)
                if i + batch_size < len(wallets):
                    await asyncio.sleep(batch_delay)

            await asyncio.sleep(POLL_INTERVAL)

    # ──────────────────────────────────────────────────────────────────
    # Polling
    # ──────────────────────────────────────────────────────────────────

    async def _poll_wallet(self, wallet: str, slot: _KeySlot):
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method":  "getSignaturesForAddress",
                "params":  [wallet, {"limit": 5}]
            }
            async with self._session.post(
                slot.url, json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data    = await response.json(content_type=None)
                headers = response.headers

            slot.record_success(cost=1, headers=headers)

            if not isinstance(data, dict) or "error" in data:
                err = data.get("error", {}) if isinstance(data, dict) else {}
                if "max usage" in str(err.get("message", "")).lower():
                    slot.record_error(is_exhausted_error=True)
                return

            await self._process_signatures(data.get("result", []), wallet, slot.url, slot)

        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
            slot.record_error(is_exhausted_error=False)
            logger.debug(f"[Parallel] {slot.label} Fehler bei {wallet[:8]}...: {type(e).__name__}")
        except Exception as e:
            logger.error(f"[Parallel] Unerwarteter Fehler: {e}", exc_info=True)

    async def _poll_wallet_public(self, wallet: str):
        url = self._next_public_url()
        if not url:
            return
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method":  "getSignaturesForAddress",
                "params":  [wallet, {"limit": 5}]
            }
            async with self._session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=6)
            ) as response:
                data = await response.json(content_type=None)

            self._public_failures[url] = 0
            if not isinstance(data, dict) or "error" in data:
                return
            await self._process_signatures(data.get("result", []), wallet, url, slot=None)

        except Exception as e:
            self._public_failures[url] = self._public_failures.get(url, 0) + 1
            logger.debug(f"[Parallel] Public Fehler {wallet[:8]}...: {type(e).__name__}")

    async def _process_signatures(self, signatures: list, wallet: str, url: str, slot: Optional[_KeySlot]):
        if not isinstance(signatures, list):
            return

        new_sigs = []
        for sig_info in signatures:
            sig = sig_info.get("signature")
            if sig and sig not in self.seen_signatures:
                self.seen_signatures.add(sig)
                new_sigs.append(sig)

        if not new_sigs:
            return

        # Initial load ignorieren
        initial_done = slot is not None  # Fallback-Task hat kein Slot-Tracking -> immer verarbeiten
        if self.ignore_initial_txs and not initial_done:
            return

        src = slot.label if slot else "Public"
        logger.debug(f"[Parallel] {wallet[:8]}... {len(new_sigs)} neue TX(s) [{src}]")

        for sig in new_sigs:
            await self._fetch_and_process(sig, wallet, url, slot)

    async def _fetch_and_process(self, signature: str, wallet: str, url: str, slot: Optional[_KeySlot]):
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method":  "getTransaction",
                "params":  [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            }
            async with self._session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json(content_type=None)

            if slot:
                slot.record_success(cost=1)

            if not isinstance(data, dict) or "error" in data:
                return

            tx = data.get("result")
            if not tx:
                return

            trade_event = self.extract_trade(tx, wallet, signature)
            if trade_event:
                await self._emit_trade(trade_event)

        except Exception as e:
            logger.error(f"[Parallel] _fetch_and_process Fehler: {e}", exc_info=True)

    # ──────────────────────────────────────────────────────────────────
    # Hilfsfunktionen
    # ──────────────────────────────────────────────────────────────────

    def _next_public_url(self) -> Optional[str]:
        for _ in range(len(self._public_endpoints)):
            ep = next(self._public_cycle)
            if self._public_failures.get(ep, 0) < 5:
                return ep
        self._public_failures = {ep: 0 for ep in self._public_endpoints}
        return self._public_endpoints[0] if self._public_endpoints else None

    def _print_credit_summary(self):
        print()
        print("[Parallel] Credit-Zusammenfassung:")
        for slot in self._key_slots:
            print(f"  {slot.status_str()}")

    def extract_trade(self, tx: dict, wallet: str, signature: str) -> Optional[TradeEvent]:
        """Identisch zu SolanaWebSocketSource.extract_trade."""
        try:
            meta          = tx.get("meta", {})
            pre_balances  = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])

            if not pre_balances and not post_balances:
                return None

            pre, post = {}, {}
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
                    amount=abs(asset_delta), source="helius_parallel",
                    raw_tx={"signature": signature, "meta": meta}
                )
            elif asset_deltas:
                token, delta = max(asset_deltas.items(), key=lambda x: abs(x[1]))
                return TradeEvent(
                    wallet=wallet, token=token,
                    side="BUY" if delta > 0 else "SELL",
                    amount=abs(delta), source="helius_parallel",
                    raw_tx={"signature": signature, "meta": meta}
                )
        except Exception as e:
            logger.error(f"[Parallel] extract_trade Fehler: {e}", exc_info=True)
        return None

    async def _emit_trade(self, trade_event: TradeEvent):
        if self.on_trade:
            if asyncio.iscoroutinefunction(self.on_trade):
                await self.on_trade(trade_event)
            else:
                self.on_trade(trade_event)
