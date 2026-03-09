"""
Connection Monitor Runner
────────────────────────────────────────────────────────────────────────
Startet nur den ConnectionHealthMonitor – ohne Trading-Logik.
Nützlich um die RPC-Verbindung zu testen oder dauerhaft zu überwachen.

python main.py connection_monitor
"""
import asyncio
import signal
import sys
import logging
from datetime import datetime

from config.network import RPC_HTTP_ENDPOINTS, NETWORK_MAINNET
from trading.connection_monitor import ConnectionHealthMonitor

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class ConnectionMonitorRunner:

    CHECK_INTERVAL = 5.0  # Sekunden zwischen RPC-Pings

    def __init__(self):
        self.shutting_down = False
        self.monitor: ConnectionHealthMonitor = None
        self.ping_task: asyncio.Task = None
        self.rpc_url: str = RPC_HTTP_ENDPOINTS[NETWORK_MAINNET]

    async def run(self):
        print()
        print("=" * 70)
        print("🛡️  CONNECTION HEALTH MONITOR")
        print("=" * 70)
        print(f"   RPC Endpoint: {self.rpc_url}")
        print(f"   Ping Interval: {self.CHECK_INTERVAL:.0f}s")
        print(f"   Emergency Threshold: 30s")
        print("=" * 70)
        print()
        print("   Press CTRL+C to stop")
        print()

        self.monitor = ConnectionHealthMonitor(
            emergency_callback=self._on_emergency,
            reconnect_callback=self._on_reconnect,
            failure_threshold_seconds=30,
            check_interval=self.CHECK_INTERVAL,
        )

        signal.signal(signal.SIGINT, self._signal_handler)

        await self.monitor.start()
        self.ping_task = asyncio.create_task(self._ping_loop())

        try:
            await self.ping_task
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    # ─────────────────────────────────────────────────────────────────────
    # PING LOOP
    # ─────────────────────────────────────────────────────────────────────

    async def _ping_loop(self):
        """Pingt den RPC-Endpunkt regelmäßig und meldet Status an Monitor."""
        import aiohttp

        logger.info("[ConnectionMonitor] Ping loop started")

        while not self.shutting_down:
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getHealth",
                    }
                    async with session.post(
                        self.rpc_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        data = await resp.json()
                        if "error" not in data:
                            self.monitor.record_success()
                            status = self.monitor.get_status()
                            ts = datetime.now().strftime("%H:%M:%S")
                            print(
                                f"  ✅ [{ts}]  Connected"
                                f"  |  Disconnections: {status['total_disconnections']}"
                                f"  |  Failures: {status['consecutive_failures']}"
                            )
                        else:
                            raise ValueError(f"RPC error: {data['error']}")

            except Exception as e:
                self.monitor.record_failure()
                status = self.monitor.get_status()
                ts = datetime.now().strftime("%H:%M:%S")
                print(
                    f"  ❌ [{ts}]  Disconnected  ({e})"
                    f"  |  Consecutive failures: {status['consecutive_failures']}"
                )

            await asyncio.sleep(self.CHECK_INTERVAL)

    # ─────────────────────────────────────────────────────────────────────
    # CALLBACKS
    # ─────────────────────────────────────────────────────────────────────

    async def _on_emergency(self):
        print()
        print("=" * 70)
        print("🚨 EMERGENCY THRESHOLD REACHED – Connection lost for > 30s")
        print("   (Kein Trading aktiv – nur Monitoring)")
        print("=" * 70)
        print()

    async def _on_reconnect(self):
        print()
        print("🔄 Reconnected – Connection restored")
        print()

    # ─────────────────────────────────────────────────────────────────────
    # SIGNAL HANDLER & SHUTDOWN
    # ─────────────────────────────────────────────────────────────────────

    def _signal_handler(self, signum, frame):
        if self.shutting_down:
            return
        print("\n\n🛑 Stopping...")
        self.shutting_down = True
        if self.ping_task:
            self.ping_task.cancel()

    async def _shutdown(self):
        if self.monitor:
            self.monitor.stop()

        status = self.monitor.get_status() if self.monitor else {}

        print()
        print("=" * 70)
        print("📊 CONNECTION MONITOR – SESSION ENDED")
        print("=" * 70)
        print(f"   Final Status:         {'Connected' if status.get('connected') else 'Disconnected'}")
        print(f"   Total Disconnections: {status.get('total_disconnections', 0)}")
        print(f"   Emergency triggered:  {'Yes ⚠️' if status.get('emergency_triggered') else 'No'}")
        if status.get('last_success'):
            print(f"   Last Success:         {status['last_success'][:19]}")
        if status.get('last_failure'):
            print(f"   Last Failure:         {status['last_failure'][:19]}")
        print("=" * 70)
        print()


async def main():
    runner = ConnectionMonitorRunner()
    await runner.run()


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
