"""
Connection Health Monitor - Erkennt Netzwerkausfälle
Schließt automatisch alle Positionen bei längeren Ausfällen
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ConnectionHealthMonitor:
    """
    Überwacht die Netzwerkverbindung zum RPC Endpoint
    Bei Ausfall  Emergency Exit aller Positionen
    """
    
    def __init__(
        self,
        emergency_callback: Callable,
        failure_threshold_seconds: int = 30,  # Nach 30s kontinuierlichen Errors  Emergency
        check_interval: float = 5.0,  # Alle 5s Status prüfen
        reconnect_callback: Optional[Callable] = None,  #  NEU: Callback bei Reconnect
    ):
        self.emergency_callback = emergency_callback
        self.reconnect_callback = reconnect_callback  #  NEU
        self.failure_threshold = timedelta(seconds=failure_threshold_seconds)
        self.check_interval = check_interval
        
        # Status Tracking
        self.last_success: Optional[datetime] = None
        self.last_failure: Optional[datetime] = None
        self.consecutive_failures = 0
        self.is_connected = True
        self.emergency_triggered = False
        self.running = False
        
        #  Zähle Anzahl der Verbindungsabbrüche
        self.total_disconnections = 0
        
        logger.info(
            f"[ConnectionMonitor] Initialized "
            f"(threshold={failure_threshold_seconds}s, check={check_interval}s)"
        )
        if reconnect_callback:
            logger.info(f"[ConnectionMonitor] Reconnect callback enabled")
    
    def record_success(self):
        """Erfolgreiches RPC Request  Reset Fehler-Counter"""
        now = datetime.now()
        
        # War vorher disconnected?
        if not self.is_connected:
            duration = (now - self.last_failure).total_seconds() if self.last_failure else 0
            logger.info(
                f"[ConnectionMonitor]  CONNECTION RESTORED "
                f"(offline for {duration:.1f}s)"
            )
            
            #  NEU: Trigger Reconnect Callback
            if self.reconnect_callback and not self.emergency_triggered:
                logger.info(f"[ConnectionMonitor]  Checking for missed SELLs...")
                try:
                    if asyncio.iscoroutinefunction(self.reconnect_callback):
                        asyncio.create_task(self.reconnect_callback())
                    else:
                        self.reconnect_callback()
                except Exception as e:
                    logger.error(f"[ConnectionMonitor] Reconnect callback failed: {e}")
        
        self.last_success = now
        self.consecutive_failures = 0
        self.is_connected = True
    
    def record_failure(self):
        """Fehlgeschlagenes RPC Request  Zähle Fehler"""
        now = datetime.now()
        self.last_failure = now
        self.consecutive_failures += 1
        
        # Bei erstem Fehler nach Success  NEUER Verbindungsabbruch!
        if self.is_connected:
            self.total_disconnections += 1
            logger.warning(
                f"[ConnectionMonitor]   CONNECTION ISSUE DETECTED "
                f"(disconnection #{self.total_disconnections})"
            )
            self.is_connected = False
    
    async def monitor_loop(self):
        """
        Hauptloop: Prüft regelmäßig Verbindungsstatus
        Triggert Emergency Exit bei zu langer Offline-Zeit
        """
        self.running = True
        logger.info("[ConnectionMonitor] Started monitoring")
        
        try:
            while self.running:
                await asyncio.sleep(self.check_interval)
                
                # Prüfe ob wir bereits Emergency getriggert haben
                if self.emergency_triggered:
                    continue
                
                # Keine Failures? Alles OK
                if self.is_connected:
                    continue
                
                # Wie lange ist letzte Success her?
                if not self.last_success:
                    # Noch nie connected? Warte noch...
                    continue
                
                offline_duration = datetime.now() - self.last_success
                
                # Threshold überschritten?
                if offline_duration > self.failure_threshold:
                    logger.error(
                        f"[ConnectionMonitor]  CRITICAL: Connection lost for "
                        f"{offline_duration.total_seconds():.1f}s "
                        f"(threshold: {self.failure_threshold.total_seconds()}s)"
                    )
                    logger.error(
                        f"[ConnectionMonitor]  TRIGGERING EMERGENCY EXIT"
                    )
                    
                    self.emergency_triggered = True
                    
                    # Trigger Emergency Callback
                    try:
                        if asyncio.iscoroutinefunction(self.emergency_callback):
                            await self.emergency_callback()
                        else:
                            self.emergency_callback()
                    except Exception as e:
                        logger.error(f"[ConnectionMonitor] Emergency callback failed: {e}")
                
                else:
                    # Noch innerhalb Threshold - warne aber
                    remaining = self.failure_threshold - offline_duration
                    logger.warning(
                        f"[ConnectionMonitor]  Offline for {offline_duration.total_seconds():.1f}s "
                        f"(emergency in {remaining.total_seconds():.1f}s)"
                    )
        
        except Exception as e:
            logger.error(f"[ConnectionMonitor] Monitor loop crashed: {e}")
        
        finally:
            logger.info("[ConnectionMonitor] Stopped monitoring")
    
    async def start(self):
        """Startet Monitoring im Hintergrund"""
        asyncio.create_task(self.monitor_loop())
    
    def stop(self):
        """Stoppt Monitoring"""
        self.running = False
    
    def get_status(self) -> dict:
        """Gibt aktuellen Status zurück"""
        now = datetime.now()
        
        offline_time = None
        if not self.is_connected and self.last_success:
            offline_time = (now - self.last_success).total_seconds()
        
        return {
            "connected": self.is_connected,
            "total_disconnections": self.total_disconnections,
            "consecutive_failures": self.consecutive_failures,
            "offline_seconds": offline_time,
            "emergency_triggered": self.emergency_triggered,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
        }
