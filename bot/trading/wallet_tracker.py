"""
Wallet Tracker - Performance-Datenbank für Wallets
Speichert Trade-Historie pro Wallet und berechnet Confidence Score
"""
import sqlite3
import logging
import math
import statistics
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DB_PATH = "data/wallet_performance.db"


@dataclass
class WalletTrade:
    """Ein Trade eines einzelnen Wallets"""
    wallet: str
    token: str
    side: str          # BUY / SELL
    amount: float
    price_eur: float
    value_eur: float
    pnl_eur: Optional[float]
    pnl_percent: Optional[float]
    timestamp: datetime
    session_id: str
    price_missing: bool = False  # True wenn Preis nicht abrufbar war


@dataclass
class WalletStats:
    """Statistiken eines Wallets"""
    wallet: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl_eur: float
    avg_pnl_eur: float
    win_rate: float
    confidence_score: float   # 0.0 – 1.0
    last_updated: datetime


# Strategie-spezifische SL/TP Fallback-Werte
# Werden genutzt solange ein Wallet noch keine dynamischen SL/TP Werte hat
# Format: (stop_loss_pct, take_profit_pct)
STRATEGY_SL_TP_DEFAULTS = {
    'ASYMMETRIC':  (-35.0, 150.0),  # Große Gewinne, enge Verluste
    'RUNNER':      (-50.0, 175.0),  # Alles oder nichts
    'SCALPER':     (-20.0,  40.0),  # Schnelle kleine Gewinne
    'LOSS_MAKER':  (-25.0,  50.0),  # Konservativ
    'MIXED':       (-50.0, 100.0),  # Globale Defaults
    'UNKNOWN':     (-50.0, 100.0),  # Noch kein Label
}

# Globale Defaults als letzter Fallback
GLOBAL_SL_DEFAULT = -50.0
GLOBAL_TP_DEFAULT = 100.0

# Positionsgröße für relative P&L Berechnung
POSITION_SIZE_EUR = 200.0  # 1000 EUR * 20%


class WalletTracker:
    """
    Verwaltet die Performance-Datenbank für Wallets.

    Confidence Score:
        - Win Rate:    45% Gewicht
        - Avg P&L:     35% Gewicht (relativ zur Positionsgröße, logarithmisch)
        - Trade Count: 20% Gewicht (sättigt bei 50 Trades)
        - Minimum 5 Trades für echten Score, sonst 0.2 (unbekannt)

    Strategie-Label (ab 20 sauberen Trades):
        ASYMMETRIC  – große Gewinne, begrenzte Verluste
        RUNNER      – lässt Gewinne laufen, akzeptiert hohe Verluste
        SCALPER     – konstante kleine Gewinne, enge Verluste
        LOSS_MAKER  – überwiegend Verluste
        MIXED       – kein klares Muster
        UNKNOWN     – unter 20 saubere Trades

    Dynamisches SL/TP (ab 20 sauberen Trades mit High/Low Daten):
        TP = 25. Perzentil der Gewinn-Exits
             → 75% aller historischen Gewinne wurden sicher getriggert
        SL = 75. Perzentil der Trade-Lows (max. Drawdown der sich erholt hat)
             → verhindert vorzeitiges Rausfliegen bei typischen Drawdowns
        Fallback: Label-basierte Defaults aus STRATEGY_SL_TP_DEFAULTS
    """

    MIN_TRADES_FOR_SCORE    = 5    # Unter diesem Wert → neutraler Score 0.2
    MIN_TRADES_FOR_LABEL    = 20   # Unter diesem Wert → UNKNOWN Label
    MIN_TRADES_FOR_DYNAMIC  = 20   # Unter diesem Wert → Label-Defaults statt dynamisch

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()
        logger.info(f"[WalletTracker] Initialized ({db_path})")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Erstellt Tabellen falls nicht vorhanden, migriert bestehende DBs."""
        conn = self._connect()
        cursor = conn.cursor()

        # Wallet Trades Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL,
                wallet          TEXT NOT NULL,
                token           TEXT NOT NULL,
                side            TEXT NOT NULL,
                amount          REAL NOT NULL,
                price_eur       REAL NOT NULL,
                value_eur       REAL NOT NULL,
                pnl_eur         REAL,
                pnl_percent     REAL,
                price_missing   INTEGER DEFAULT 0,
                max_price_pct   REAL,
                min_price_pct   REAL,
                timestamp       TEXT NOT NULL
            )
        """)

        # Migrationen für bestehende DBs
        cursor.execute("PRAGMA table_info(wallet_trades)")
        trade_cols = [row['name'] for row in cursor.fetchall()]
        for col, typedef in [
            ('price_missing', 'INTEGER DEFAULT 0'),
            ('max_price_pct', 'REAL'),
            ('min_price_pct', 'REAL'),
        ]:
            if col not in trade_cols:
                cursor.execute(f"ALTER TABLE wallet_trades ADD COLUMN {col} {typedef}")
                logger.info(f"[WalletTracker] Migrated: added wallet_trades.{col}")

        # Wallet Stats / Confidence Cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_stats (
                wallet              TEXT PRIMARY KEY,
                total_trades        INTEGER DEFAULT 0,
                winning_trades      INTEGER DEFAULT 0,
                losing_trades       INTEGER DEFAULT 0,
                total_pnl_eur       REAL DEFAULT 0.0,
                avg_pnl_eur         REAL DEFAULT 0.0,
                win_rate            REAL DEFAULT 0.0,
                confidence_score    REAL DEFAULT 0.2,
                strategy_label      TEXT DEFAULT 'UNKNOWN',
                dynamic_sl          REAL,
                dynamic_tp          REAL,
                last_updated        TEXT NOT NULL
            )
        """)

        # Migrationen für bestehende DBs
        cursor.execute("PRAGMA table_info(wallet_stats)")
        stat_cols = [row['name'] for row in cursor.fetchall()]
        for col, typedef in [
            ('strategy_label', "TEXT DEFAULT 'UNKNOWN'"),
            ('dynamic_sl',     'REAL'),
            ('dynamic_tp',     'REAL'),
        ]:
            if col not in stat_cols:
                cursor.execute(f"ALTER TABLE wallet_stats ADD COLUMN {col} {typedef}")
                logger.info(f"[WalletTracker] Migrated: added wallet_stats.{col}")

        # Inaktivitäts-Tags pro Wallet
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_inactivity_tags (
                wallet     TEXT PRIMARY KEY,
                tags       INTEGER DEFAULT 0,
                updated    TEXT NOT NULL
            )
        """)

        # Indizes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wallet_trades_wallet
            ON wallet_trades(wallet)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wallet_trades_session
            ON wallet_trades(session_id)
        """)

        conn.commit()
        conn.close()
        logger.info("[WalletTracker] Database initialized")

    # ──────────────────────────────────────────────────────────────────────
    # TRADE RECORDING
    # ──────────────────────────────────────────────────────────────────────

    def record_buy(self, session_id: str, wallet: str, token: str,
                   amount: float, price_eur: float) -> int:
        """Speichert einen BUY Trade. Gibt die Trade-ID zurück."""
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO wallet_trades
            (session_id, wallet, token, side, amount, price_eur, value_eur, timestamp)
            VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?)
        """, (
            session_id, wallet, token,
            amount, price_eur, amount * price_eur,
            datetime.now().isoformat()
        ))

        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return trade_id

    def record_sell(self, session_id: str, wallet: str, token: str,
                    amount: float, price_eur: float,
                    entry_price_eur: float,
                    price_missing: bool = False,
                    max_price_pct: Optional[float] = None,
                    min_price_pct: Optional[float] = None) -> None:
        """
        Speichert einen SELL Trade und aktualisiert Wallet-Stats.

        max_price_pct: höchster Preis während der Position in % (z.B. +120.0)
        min_price_pct: niedrigster Preis während der Position in % (z.B. -38.0)
        price_missing=True markiert Trades bei denen kein Preis abrufbar war
        """
        pnl_eur = (price_eur - entry_price_eur) * amount
        pnl_percent = ((price_eur - entry_price_eur) / entry_price_eur * 100) if entry_price_eur > 0 else 0

        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO wallet_trades
            (session_id, wallet, token, side, amount, price_eur, value_eur,
             pnl_eur, pnl_percent, price_missing, max_price_pct, min_price_pct, timestamp)
            VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, wallet, token,
            amount, price_eur, amount * price_eur,
            pnl_eur, pnl_percent,
            1 if price_missing else 0,
            max_price_pct, min_price_pct,
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        self._recalculate_stats(wallet)

    # ──────────────────────────────────────────────────────────────────────
    # STATS & CONFIDENCE
    # ──────────────────────────────────────────────────────────────────────

    def _recalculate_stats(self, wallet: str):
        """Berechnet Stats, Confidence Score, Label und dynamisches SL/TP neu."""
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT pnl_eur, pnl_percent, max_price_pct, min_price_pct
            FROM wallet_trades
            WHERE wallet = ? AND side = 'SELL' AND pnl_eur IS NOT NULL
        """, (wallet,))
        rows = cursor.fetchall()

        if not rows:
            conn.close()
            return

        total_trades = len(rows)
        winning      = [r for r in rows if r['pnl_eur'] > 0]
        losing       = [r for r in rows if r['pnl_eur'] <= 0]

        total_pnl = sum(r['pnl_eur'] for r in rows)
        avg_pnl   = total_pnl / total_trades
        win_rate  = len(winning) / total_trades

        # ── Confidence Score ─────────────────────────────────────────────
        if total_trades < self.MIN_TRADES_FOR_SCORE:
            confidence = 0.2
        else:
            wr_score    = win_rate * 0.45
            count_score = min(total_trades / 50, 1.0) * 0.20
            avg_pnl_pct = (avg_pnl / POSITION_SIZE_EUR) * 100
            avg_pnl_pct_pos = max(avg_pnl_pct, 0.0)
            pnl_score = (math.log2(1 + avg_pnl_pct_pos / 25) / math.log2(21)) * 0.35
            pnl_score = min(pnl_score, 0.35)
            confidence = round(max(0.0, min(1.0, wr_score + count_score + pnl_score)), 4)

        # ── Strategie-Label ──────────────────────────────────────────────
        strategy_label = self._calculate_strategy_label(wallet, conn)

        # ── Dynamisches SL/TP ────────────────────────────────────────────
        dynamic_sl, dynamic_tp = self._calculate_dynamic_sl_tp(wallet, conn)

        cursor.execute("""
            INSERT INTO wallet_stats
                (wallet, total_trades, winning_trades, losing_trades,
                 total_pnl_eur, avg_pnl_eur, win_rate, confidence_score,
                 strategy_label, dynamic_sl, dynamic_tp, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet) DO UPDATE SET
                total_trades     = excluded.total_trades,
                winning_trades   = excluded.winning_trades,
                losing_trades    = excluded.losing_trades,
                total_pnl_eur    = excluded.total_pnl_eur,
                avg_pnl_eur      = excluded.avg_pnl_eur,
                win_rate         = excluded.win_rate,
                confidence_score = excluded.confidence_score,
                strategy_label   = excluded.strategy_label,
                dynamic_sl       = excluded.dynamic_sl,
                dynamic_tp       = excluded.dynamic_tp,
                last_updated     = excluded.last_updated
        """, (
            wallet, total_trades, len(winning), len(losing),
            total_pnl, avg_pnl, win_rate, confidence,
            strategy_label, dynamic_sl, dynamic_tp,
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        logger.debug(
            f"[WalletTracker] {wallet[:8]}... → "
            f"conf={confidence:.2f} | wr={win_rate:.0%} | trades={total_trades} | "
            f"avg_pnl={avg_pnl:+.2f} EUR | label={strategy_label} | "
            f"sl={dynamic_sl} tp={dynamic_tp}"
        )

    def _calculate_strategy_label(self, wallet: str, conn) -> str:
        """
        Berechnet das Strategie-Label aus sauberen Trades.
        Berücksichtigt auch High/Low Daten für präzisere Klassifizierung.
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pnl_percent, pnl_eur, max_price_pct, min_price_pct
            FROM wallet_trades
            WHERE wallet = ? AND side = 'SELL'
              AND pnl_eur IS NOT NULL
              AND price_missing = 0
              AND pnl_percent != 0
            ORDER BY timestamp DESC
        """, (wallet,))
        trades = cursor.fetchall()

        if len(trades) < self.MIN_TRADES_FOR_LABEL:
            return 'UNKNOWN'

        pcts   = [t['pnl_percent'] for t in trades]
        wins   = [p for p in pcts if p > 0]
        losses = [p for p in pcts if p < 0]

        win_rate  = len(wins) / len(pcts)
        avg_win   = statistics.mean(wins)   if wins   else 0.0
        avg_loss  = statistics.mean(losses) if losses else 0.0

        gross_profit  = sum(t['pnl_eur'] for t in trades if t['pnl_eur'] > 0)
        gross_loss    = abs(sum(t['pnl_eur'] for t in trades if t['pnl_eur'] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0

        # High/Low Daten für präzisere Klassifizierung
        # Drawdown-Toleranz: Wallet hält Drawdowns aus bevor es sich erholt
        lows_available = [t['min_price_pct'] for t in trades if t['min_price_pct'] is not None]
        highs_available = [t['max_price_pct'] for t in trades if t['max_price_pct'] is not None]

        # Median Drawdown = typischer maximaler Einbruch während einer Position
        median_drawdown = statistics.median(lows_available) if lows_available else avg_loss
        # Median High = wie weit geht ein Token typischerweise ins Plus bevor Wallet verkauft
        median_high = statistics.median(highs_available) if highs_available else avg_win

        # Klassifizierung
        if win_rate < 0.15:
            label = 'LOSS_MAKER'

        elif avg_win > 80 and abs(avg_loss) < 45 and profit_factor >= 1.0:
            # ASYMMETRIC: Gute Gewinne, begrenzte Verluste
            # Zusatz: median_drawdown sollte moderat sein (kein extremes Risiko)
            label = 'ASYMMETRIC'

        elif avg_win > 60 and abs(avg_loss) >= 35:
            # Potentieller RUNNER – Wallet akzeptiert hohe Verluste
            # Entscheidend: Hält es Drawdowns aus (median_drawdown tief) und
            # lässt es wirklich laufen (median_high hoch)?
            if lows_available and highs_available:
                # Echter RUNNER: median_high deutlich über avg_exit_win
                # und Wallet hält Drawdowns > 40% aus
                if median_high > avg_win * 0.8 and abs(median_drawdown) > 30:
                    label = 'RUNNER'
                elif abs(median_drawdown) <= 30:
                    # Hohe Verlust-Exits aber keine tiefen Drawdowns → eher MIXED
                    label = 'MIXED'
                else:
                    label = 'RUNNER'
            else:
                label = 'RUNNER'

        elif avg_win <= 50 and abs(avg_loss) <= 25 and win_rate >= 0.50:
            # SCALPER: Kleine Gewinne, enge Verluste, hohe Win-Rate
            # Zusatz: median_drawdown sollte ebenfalls eng sein
            if lows_available and abs(median_drawdown) <= 35:
                label = 'SCALPER'
            elif lows_available and abs(median_drawdown) > 35:
                # Wartet auf sichere Trades aber hält gelegentlich starke Drawdowns aus
                label = 'MIXED'
            else:
                label = 'SCALPER'

        else:
            label = 'MIXED'

        logger.debug(
            f"[WalletTracker] {wallet[:8]}... strategy={label} "
            f"wr={win_rate:.0%} avg_win={avg_win:+.1f}% avg_loss={avg_loss:+.1f}% "
            f"pf={profit_factor:.2f} median_dd={median_drawdown:.1f}% "
            f"median_high={median_high:.1f}% (n={len(trades)})"
        )
        return label

    def _calculate_dynamic_sl_tp(self, wallet: str, conn) -> Tuple[Optional[float], Optional[float]]:
        """
        Berechnet dynamisches SL/TP aus historischen Trade-Daten.

        TP = 25. Perzentil der Gewinn-Exits
             → 75% aller historischen Gewinne lagen über diesem Wert
             → konservativ, triggert sicher

        SL = 75. Perzentil der Trade-Lows (min_price_pct)
             → 75% der Trades hatten einen Drawdown der nicht tiefer ging
             → SL liegt unter dem typischen Drawdown, verhindert vorzeitiges Rausfliegen
             → Fallback auf 75. Perzentil der Verlust-Exits wenn keine Low-Daten vorhanden

        Gibt (None, None) zurück wenn zu wenig Daten.
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pnl_percent, min_price_pct
            FROM wallet_trades
            WHERE wallet = ? AND side = 'SELL'
              AND pnl_eur IS NOT NULL
              AND price_missing = 0
              AND pnl_percent != 0
            ORDER BY timestamp DESC
        """, (wallet,))
        trades = cursor.fetchall()

        if len(trades) < self.MIN_TRADES_FOR_DYNAMIC:
            return (None, None)

        pcts   = [t['pnl_percent'] for t in trades]
        wins   = sorted([p for p in pcts if p > 0])
        losses = sorted([p for p in pcts if p < 0])  # aufsteigend (negativste zuerst)

        # ── Take-Profit: 25. Perzentil der Gewinne ──────────────────────
        if wins:
            tp_idx = max(0, int(len(wins) * 0.25) - 1)
            raw_tp = wins[tp_idx]
            # Sicherheitsgrenzen: TP mindestens +20%, maximal +300%
            dynamic_tp = round(max(20.0, min(300.0, raw_tp)), 1)
        else:
            dynamic_tp = None

        # ── Stop-Loss: 75. Perzentil der Trade-Lows ─────────────────────
        lows = [t['min_price_pct'] for t in trades if t['min_price_pct'] is not None]

        if lows:
            lows_sorted = sorted(lows)  # aufsteigend (negativste zuerst)
            sl_idx = min(len(lows_sorted) - 1, int(len(lows_sorted) * 0.75))
            raw_sl = lows_sorted[sl_idx]
            # Sicherheitsgrenzen: SL mindestens -10%, maximal -80%
            # Ein Wallet das typischerweise -60% Drawdowns aushält bekommt SL bei -65%
            dynamic_sl = round(max(-80.0, min(-10.0, raw_sl * 1.1)), 1)  # 10% Puffer
        elif losses:
            # Fallback: 75. Perzentil der Verlust-Exits
            sl_idx = min(len(losses) - 1, int(len(losses) * 0.75))
            raw_sl = losses[sl_idx]
            dynamic_sl = round(max(-80.0, min(-10.0, raw_sl)), 1)
        else:
            dynamic_sl = None

        logger.debug(
            f"[WalletTracker] {wallet[:8]}... dynamic SL={dynamic_sl} TP={dynamic_tp} "
            f"(wins={len(wins)}, losses={len(losses)}, lows={len(lows)})"
        )
        return (dynamic_sl, dynamic_tp)

    # ──────────────────────────────────────────────────────────────────────
    # SL/TP GETTER
    # ──────────────────────────────────────────────────────────────────────

    def get_sl_tp_for_wallet(self, wallet: str) -> tuple:
        """
        Gibt (stop_loss_pct, take_profit_pct) für ein Wallet zurück.

        Priorität:
        1. Dynamische Werte aus historischen Daten (wenn vorhanden)
        2. Label-basierte Defaults aus STRATEGY_SL_TP_DEFAULTS
        3. Globale Defaults
        """
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT strategy_label, dynamic_sl, dynamic_tp FROM wallet_stats WHERE wallet = ?",
            (wallet,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return (GLOBAL_SL_DEFAULT, GLOBAL_TP_DEFAULT)

        # Dynamische Werte haben Priorität
        if row['dynamic_sl'] is not None and row['dynamic_tp'] is not None:
            return (row['dynamic_sl'], row['dynamic_tp'])

        # Fallback: Label-Defaults
        label = row['strategy_label'] or 'UNKNOWN'
        return STRATEGY_SL_TP_DEFAULTS.get(label, (GLOBAL_SL_DEFAULT, GLOBAL_TP_DEFAULT))

    def get_sl_tp_for_wallets(self, wallets: list) -> tuple:
        """
        Gibt gemittelten (stop_loss_pct, take_profit_pct) für mehrere Wallets.
        Bevorzugt dynamische Werte. Ignoriert UNKNOWN ohne dynamische Werte
        falls andere Wallets bessere Daten haben.
        """
        sl_tp_values = []
        for wallet in wallets:
            sl, tp = self.get_sl_tp_for_wallet(wallet)
            label = self.get_strategy_label(wallet)
            # Nur einbeziehen wenn dynamisch ODER nicht UNKNOWN
            if label != 'UNKNOWN' or self._has_dynamic_sl_tp(wallet):
                sl_tp_values.append((sl, tp))

        if not sl_tp_values:
            return (GLOBAL_SL_DEFAULT, GLOBAL_TP_DEFAULT)

        avg_sl = sum(v[0] for v in sl_tp_values) / len(sl_tp_values)
        avg_tp = sum(v[1] for v in sl_tp_values) / len(sl_tp_values)
        return (round(avg_sl, 1), round(avg_tp, 1))

    def _has_dynamic_sl_tp(self, wallet: str) -> bool:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT dynamic_sl, dynamic_tp FROM wallet_stats WHERE wallet = ?",
            (wallet,)
        )
        row = cursor.fetchone()
        conn.close()
        return row is not None and row['dynamic_sl'] is not None and row['dynamic_tp'] is not None

    def get_strategy_label(self, wallet: str) -> str:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT strategy_label FROM wallet_stats WHERE wallet = ?",
            (wallet,)
        )
        row = cursor.fetchone()
        conn.close()
        return row['strategy_label'] if row else 'UNKNOWN'

    def get_confidence(self, wallet: str) -> float:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT confidence_score FROM wallet_stats WHERE wallet = ?",
            (wallet,)
        )
        row = cursor.fetchone()
        conn.close()
        return row['confidence_score'] if row else 0.2

    def get_confidence_map(self, wallets: List[str]) -> Dict[str, float]:
        if not wallets:
            return {}
        conn = self._connect()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in wallets)
        cursor.execute(
            f"SELECT wallet, confidence_score FROM wallet_stats WHERE wallet IN ({placeholders})",
            wallets
        )
        rows = cursor.fetchall()
        conn.close()
        result = {w: 0.2 for w in wallets}
        for row in rows:
            result[row['wallet']] = row['confidence_score']
        return result

    def get_stats(self, wallet: str) -> Optional[WalletStats]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wallet_stats WHERE wallet = ?", (wallet,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return WalletStats(
            wallet=row['wallet'],
            total_trades=row['total_trades'],
            winning_trades=row['winning_trades'],
            losing_trades=row['losing_trades'],
            total_pnl_eur=row['total_pnl_eur'],
            avg_pnl_eur=row['avg_pnl_eur'],
            win_rate=row['win_rate'],
            confidence_score=row['confidence_score'],
            last_updated=datetime.fromisoformat(row['last_updated'])
        )

    def get_all_stats(self) -> List[WalletStats]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wallet_stats ORDER BY confidence_score DESC")
        rows = cursor.fetchall()
        conn.close()
        return [
            WalletStats(
                wallet=r['wallet'],
                total_trades=r['total_trades'],
                winning_trades=r['winning_trades'],
                losing_trades=r['losing_trades'],
                total_pnl_eur=r['total_pnl_eur'],
                avg_pnl_eur=r['avg_pnl_eur'],
                win_rate=r['win_rate'],
                confidence_score=r['confidence_score'],
                last_updated=datetime.fromisoformat(r['last_updated'])
            )
            for r in rows
        ]

    def get_session_trades(self, session_id: str) -> List[dict]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM wallet_trades WHERE session_id = ? ORDER BY timestamp",
            (session_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────────────────────────────
    # INAKTIVITÄTS-TAG SYSTEM
    # ──────────────────────────────────────────────────────────────────────

    INACTIVITY_TIMEOUT_DEFAULT   = 600  # 10 Minuten
    INACTIVITY_TIMEOUT_PENALIZED = 300  # 5 Minuten bei 3 Tags
    INACTIVITY_MAX_TAGS          = 3

    def get_inactivity_timeout(self, wallets: list) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in wallets)
        cursor.execute(
            f"SELECT MAX(tags) as max_tags FROM wallet_inactivity_tags WHERE wallet IN ({placeholders})",
            wallets
        )
        row = cursor.fetchone()
        conn.close()
        max_tags = row['max_tags'] if row and row['max_tags'] is not None else 0
        return self.INACTIVITY_TIMEOUT_PENALIZED if max_tags >= self.INACTIVITY_MAX_TAGS else self.INACTIVITY_TIMEOUT_DEFAULT

    def add_inactivity_tag(self, wallet: str) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO wallet_inactivity_tags (wallet, tags, updated)
            VALUES (?, 1, ?)
            ON CONFLICT(wallet) DO UPDATE SET
                tags    = MIN(tags + 1, ?),
                updated = excluded.updated
        """, (wallet, datetime.now().isoformat(), self.INACTIVITY_MAX_TAGS))
        cursor.execute("SELECT tags FROM wallet_inactivity_tags WHERE wallet = ?", (wallet,))
        new_tags = cursor.fetchone()['tags']
        conn.commit()
        conn.close()
        logger.info(f"[WalletTracker] {wallet[:8]}... inactivity tag +1 → {new_tags}/{self.INACTIVITY_MAX_TAGS}")
        return new_tags

    def remove_inactivity_tag(self, wallet: str) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE wallet_inactivity_tags
            SET tags = MAX(tags - 1, 0), updated = ?
            WHERE wallet = ?
        """, (datetime.now().isoformat(), wallet))
        cursor.execute("SELECT tags FROM wallet_inactivity_tags WHERE wallet = ?", (wallet,))
        row = cursor.fetchone()
        new_tags = row['tags'] if row else 0
        conn.commit()
        conn.close()
        logger.info(f"[WalletTracker] {wallet[:8]}... inactivity tag -1 → {new_tags}/{self.INACTIVITY_MAX_TAGS}")
        return new_tags

    def get_inactivity_tags(self, wallet: str) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT tags FROM wallet_inactivity_tags WHERE wallet = ?", (wallet,))
        row = cursor.fetchone()
        conn.close()
        return row['tags'] if row else 0
