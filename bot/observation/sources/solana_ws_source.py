"""
Solana Multi-Key Polling Source - Helius Key Rotation

Strategie: Mehrere Helius API Keys rotieren im Round-Robin.
Jeder Key hat 100k Credits/Tag.
Beispiel: 3 Keys = 300k Credits/Tag (deckt ~277k bei 54-60 Wallets ab).

Neue Keys erstellen: https://dev.helius.xyz/dashboard (kostenlos)
Keys eintragen in: config/network.py -> HELIUS_API_KEYS

Wenn alle Helius-Keys erschoepft sind, wird automatisch auf
kostenlose Public RPCs umgeschaltet (PUBLIC_FALLBACK_ENDPOINTS).

Identische Polling-Logik wie SolanaPollingSource (bewaehrt).
"""

import asyncio
import itertools
import logging
from typing import Dict, Optional, Set

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

CREDITS_PER_MONTH = 1_000_000   # Helius Free Tier: 1 Mio Credits/Monat pro Key
CREDITS_PER_DAY   = CREDITS_PER_MONTH // 30  # ~33,333/Tag (Richtwert fuer Tagesverbrauch)
POLL_INTERVAL    = 3          # Sekunden zwischen Poll-Zyklen
RPC_MAX_RPS      = 8          # Requests pro Sekunde pro Endpunkt (Helius: 8, Public: 5)
PUBLIC_MAX_RPS   = 5


class _KeySlot:
    """Verwaltet einen einzelnen Helius API Key mit Credit-Tracking."""

    def __init__(self, key: str, url: str):
        self.key            = key
        self.url            = url
        self.label          = f"Helius ...{key[-6:]}"
        self.credits        = 0        # verbrauchte Credits diesen Monat
        self.credits_remaining: Optional[int] = None  # aus Helius-Header (exakt)
        self.errors         = 0
        self.exhausted      = False
        self._month         = self._current_month()

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
            print(f"[MultiKey] {self.label}: Neuer Monat - Credits zurueckgesetzt")

    def record_success(self, cost: int = 1, headers=None):
        self._reset_if_new_month()
        self.credits += cost
        self.errors   = 0

        # Helius liefert exakte Restwerte im Response-Header
        if headers:
            # X-RateLimit-Remaining-Month oder X-Credits-Remaining
            for hdr in ('x-ratelimit-remaining-month', 'x-credits-remaining',
                        'ratelimit-remaining', 'x-ratelimit-remaining'):
                val = headers.get(hdr)
                if val is not None:
                    try:
                        self.credits_remaining = int(val)
                        # Hochrechnen: verbraucht = limit - verbleibend
                        self.credits = CREDITS_PER_MONTH - self.credits_remaining
                    except (ValueError, TypeError):
                        pass
                    break

        if self.credits >= CREDITS_PER_MONTH:
            if not self.exhausted:
                remaining = max(0, self.credits_remaining or 0)
                print(f"[MultiKey] {self.label}: Monatslimit erreicht ({self.credits:,}/{CREDITS_PER_MONTH:,}, {remaining:,} verbleibend) - naechster Key")
            self.exhausted = True
        elif self.credits % 100_000 == 0 and self.credits > 0:
            remaining = self.credits_remaining if self.credits_remaining is not None else (CREDITS_PER_MONTH - self.credits)
            print(f"[MultiKey] {self.label}: {self.credits:,}/{CREDITS_PER_MONTH:,} Credits verbraucht ({remaining:,} verbleibend)")

    def record_error(self, is_exhausted_error: bool = False):
        self._reset_if_new_month()
        self.errors += 1
        if is_exhausted_error:
            self.exhausted = True
            print(f"[MultiKey] {self.label}: Limit erschoepft - Key uebersprungen")

    def is_available(self) -> bool:
        self._reset_if_new_month()
        return not self.exhausted and self.errors < 5

    def status_str(self) -> str:
        state = "ERSCHOEPFT" if self.exhausted else ("FEHLER" if self.errors >= 5 else "OK")
        if self.credits_remaining is not None:
            # Exakter Wert aus Helius-Header verfuegbar
            pct = (self.credits_remaining / CREDITS_PER_MONTH * 100)
            return f"{self.label}: {self.credits_remaining:,} verbleibend ({pct:.0f}%)  [{state}]"
        else:
            # Schaetzung basierend auf lokalem Zaehler
            remaining = max(0, CREDITS_PER_MONTH - self.credits)
            pct       = (remaining / CREDITS_PER_MONTH * 100)
            return f"{self.label}: ~{remaining:,} verbleibend ({pct:.0f}%)  [{state}] (geschaetzt)"


class SolanaWebSocketSource(TradeSource):
    """
    Polling-Source mit Helius Multi-Key Rotation.
    Faellt automatisch auf Public RPCs zurueck wenn alle Keys erschoepft.
    Interface-kompatibel mit SolanaPollingSource.
    """

    def __init__(
        self,
        ws_url: str,          # nicht verwendet, Interface-kompatibel
        http_url: str,        # nicht verwendet, Interface-kompatibel
        wallets: list = None,
        callback=None,
        ignore_initial_txs: bool = True,
        connection_monitor=None,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 0,
    ):
        super().__init__()

        self.wallets            = list(wallets or [])
        self.ignore_initial_txs = ignore_initial_txs
        self.connection_monitor = connection_monitor
        self.poll_interval      = POLL_INTERVAL

        # Helius Keys als Slots
        self._key_slots: list[_KeySlot] = [
            _KeySlot(key, url)
            for key, url in zip(HELIUS_API_KEYS, HELIUS_HTTP_ENDPOINTS)
        ]

        # Public Fallback-Endpunkte
        self._public_endpoints  = list(PUBLIC_FALLBACK_ENDPOINTS)
        self._public_failures:  Dict[str, int] = {ep: 0 for ep in self._public_endpoints}
        self._public_cycle      = itertools.cycle(self._public_endpoints)
        self._using_fallback    = False

        # Kompatibilitaet
        self.rpc_http_url    = HELIUS_HTTP_ENDPOINTS[0] if HELIUS_HTTP_ENDPOINTS else PUBLIC_FALLBACK_ENDPOINTS[0]
        self.is_fast_polling = False
        self.watch_wallets:  Set[str] = set()

        self.running           = False
        self.connected         = False
        self.initial_load_done = False
        self.seen_signatures:  Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None

        # Key-Rotation: Round-Robin Index
        self._key_idx = 0

        if callback:
            self.on_trade = callback

        self._print_startup()

    def _print_startup(self):
        n = len(self._key_slots)
        total_month = n * CREDITS_PER_MONTH
        days_total  = total_month // 277_000 if n else 0  # Tage Dauerbetrieb
        print(f"[MultiKey] Helius Multi-Key Rotation gestartet")
        print(f"[MultiKey] {n} Key(s) -> {total_month:,} Credits/Monat  (~{days_total} Tage Dauerbetrieb)")
        for slot in self._key_slots:
            print(f"[MultiKey]   {slot.status_str()}")
        if self._public_endpoints:
            print(f"[MultiKey] Fallback: {len(self._public_endpoints)} Public RPC(s) wenn alle Keys erschoepft")
        print(f"[MultiKey] Poll-Intervall: {POLL_INTERVAL}s | Watching {len(self.wallets)} wallets")

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    async def connect(self):
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
        print("[MultiKey] Stopping...")
        self._print_credit_summary()

    def get_polling_status(self) -> dict:
        status = {
            'is_fast_polling': self.is_fast_polling,
            'watch_wallets':   list(self.watch_wallets),
            'using_fallback':  self._using_fallback,
            'keys': [
                {'label': s.label, 'credits': s.credits, 'exhausted': s.exhausted}
                for s in self._key_slots
            ],
        }
        if self.connection_monitor:
            status['connection'] = self.connection_monitor.get_status()
        return status

    def start_watching_wallets(self, wallets: list):
        self.watch_wallets   = set(wallets)
        self.is_fast_polling = True

    def stop_watching_wallets(self):
        self.watch_wallets.clear()
        self.is_fast_polling = False

    def listen(self):
        raise NotImplementedError("MultiKey Source nutzt async connect()")

    # ------------------------------------------------------------------
    # ENDPUNKT-AUSWAHL
    # ------------------------------------------------------------------

    def _next_helius_url(self) -> Optional[str]:
        """
        Gibt die URL des naechsten verfuegbaren Helius-Keys zurueck.
        Round-Robin, ueberspringt erschoepfte / fehlerhafte Keys.
        Gibt None zurueck wenn alle Keys unavailable sind.
        """
        n = len(self._key_slots)
        if n == 0:
            return None
        for _ in range(n):
            slot = self._key_slots[self._key_idx % n]
            self._key_idx += 1
            if slot.is_available():
                return slot.url
        return None

    def _next_public_url(self) -> Optional[str]:
        """Gibt naechsten Public Fallback-Endpunkt zurueck."""
        for _ in range(len(self._public_endpoints)):
            ep = next(self._public_cycle)
            if self._public_failures.get(ep, 0) < 5:
                return ep
        # Alle kaputt -> Reset
        self._public_failures = {ep: 0 for ep in self._public_endpoints}
        return self._public_endpoints[0] if self._public_endpoints else None

    def _get_endpoint(self) -> tuple[Optional[str], bool]:
        """
        Gibt (url, is_helius) zurueck.
        Helius bevorzugt, Public als Fallback.
        """
        url = self._next_helius_url()
        if url:
            if self._using_fallback:
                self._using_fallback = False
                print("[MultiKey] Helius-Key wieder verfuegbar - wechsel zurueck von Public Fallback")
            return url, True

        # Alle Helius-Keys erschoepft -> Public Fallback
        if not self._using_fallback:
            self._using_fallback = True
            print("[MultiKey] Alle Helius-Keys erschoepft - wechsle auf Public Fallback RPCs")
        return self._next_public_url(), False

    def _record_success(self, url: str, is_helius: bool, headers=None):
        if is_helius:
            slot = next((s for s in self._key_slots if s.url == url), None)
            if slot:
                slot.record_success(cost=1, headers=headers)
                # Alle N requests: kurzen Status ausgeben
                if slot.credits % 10_000 == 0 and slot.credits > 0:
                    print(f"[MultiKey] {slot.status_str()}")
        else:
            self._public_failures[url] = 0
            if self.connection_monitor:
                self.connection_monitor.record_success()

    def _record_error(self, url: str, is_helius: bool, error: Exception):
        err_str = str(error).lower()
        exhausted = "max usage" in err_str or "429" in err_str or "rate limit" in err_str
        if is_helius:
            slot = next((s for s in self._key_slots if s.url == url), None)
            if slot:
                slot.record_error(is_exhausted_error=exhausted)
        else:
            self._public_failures[url] = self._public_failures.get(url, 0) + 1
            fails = self._public_failures[url]
            if fails <= 2:
                logger.warning(f"[MultiKey] Public {url[:35]}... Fehler: {type(error).__name__} ({fails}/5)")
            elif fails == 5:
                print(f"[MultiKey] Public {url[:35]}... temporaer uebersprungen")

    def _print_credit_summary(self):
        print()
        print("[MultiKey] Credit-Zusammenfassung:")
        for slot in self._key_slots:
            print(f"  {slot.status_str()}")

    # ------------------------------------------------------------------
    # POLLING
    # ------------------------------------------------------------------

    async def _poll_all_wallets(self):
        wallets = (
            list(self.watch_wallets)
            if self.is_fast_polling and self.watch_wallets
            else list(self.wallets)
        )

        batch_size  = max(3, min(10, len(wallets) // 4 or 3))
        batch_delay = max(0.3, batch_size / RPC_MAX_RPS)

        for i in range(0, len(wallets), batch_size):
            for wallet in wallets[i:i + batch_size]:
                await self._poll_wallet(wallet)
            if i + batch_size < len(wallets):
                await asyncio.sleep(batch_delay)

        if not self.initial_load_done:
            self.initial_load_done = True
            if self.ignore_initial_txs:
                print("[MultiKey] Initial load abgeschlossen - beobachte neue Transaktionen")

    async def _poll_wallet(self, wallet: str):
        url, is_helius = self._get_endpoint()
        if not url:
            logger.warning("[MultiKey] Kein Endpunkt verfuegbar - ueberspringe Wallet")
            return

        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method":  "getSignaturesForAddress",
                "params":  [wallet, {"limit": 5}]
            }
            async with self._session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data    = await response.json(content_type=None)
                headers = response.headers

            self._record_success(url, is_helius, headers=headers)

            if not isinstance(data, dict):
                return
            if "error" in data:
                err = data["error"]
                # Helius 'max usage reached' explizit erkennen
                if isinstance(err, dict) and "max usage" in str(err.get("message", "")).lower():
                    self._record_error(url, is_helius, Exception("max usage reached"))
                else:
                    logger.debug(f"[MultiKey] RPC Error {wallet[:8]}...: {err}")
                return

            signatures = data.get("result", [])
            if not isinstance(signatures, list):
                return

            new_sigs = []
            for sig_info in signatures:
                sig = sig_info.get("signature")
                if sig and sig not in self.seen_signatures:
                    self.seen_signatures.add(sig)
                    new_sigs.append(sig)

            if not self.initial_load_done and self.ignore_initial_txs:
                return

            if new_sigs:
                src = "Helius" if is_helius else "Public"
                print(f"[MultiKey] {wallet[:8]}... {len(new_sigs)} neue TX(s)  [{src}]")
                for sig in new_sigs:
                    await self._fetch_and_process(sig, wallet, url, is_helius)

        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
            self._record_error(url, is_helius, e)
        except Exception as e:
            logger.error(f"[MultiKey] Unerwarteter Fehler bei {wallet[:8]}...: {e}", exc_info=True)

    async def _fetch_and_process(self, signature: str, wallet: str, url: str, is_helius: bool):
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

            if is_helius:
                slot = next((s for s in self._key_slots if s.url == url), None)
                if slot:
                    slot.record_success(cost=1)  # getTransaction = 1 Credit

            if not isinstance(data, dict):
                return
            if "error" in data:
                logger.debug(f"[MultiKey] getTransaction Fehler {signature[:8]}...: {data['error']}")
                return

            tx = data.get("result")
            if not tx:
                return

            trade_event = self.extract_trade(tx, wallet, signature)
            if trade_event:
                await self._emit_trade(trade_event)

        except Exception as e:
            logger.error(f"[MultiKey] _fetch_and_process Fehler: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # TRADE EXTRAKTION (identisch zu SolanaPollingSource)
    # ------------------------------------------------------------------

    def extract_trade(self, tx: dict, wallet: str, signature: str) -> Optional[TradeEvent]:
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
                    amount=abs(asset_delta), source="helius_multikey",
                    raw_tx={"signature": signature, "meta": meta}
                )
            elif asset_deltas:
                token, delta = max(asset_deltas.items(), key=lambda x: abs(x[1]))
                return TradeEvent(
                    wallet=wallet, token=token,
                    side="BUY" if delta > 0 else "SELL",
                    amount=abs(delta), source="helius_multikey",
                    raw_tx={"signature": signature, "meta": meta}
                )
        except Exception as e:
            logger.error(f"[MultiKey] extract_trade Fehler: {e}", exc_info=True)
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
