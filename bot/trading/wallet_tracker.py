"""
Wallet Tracker - Performance-Datenbank für Wallets
Speichert Trade-Historie pro Wallet und berechnet Confidence Score
"""
import sqlite3
import logging
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


# Strategie-spezifische SL/TP Defaults
# Format: (stop_loss_pct, take_profit_pct)
STRATEGY_SL_TP = {
    'ASYMMETRIC':  (-35.0, 150.0),  # Große Gewinne, enge Verluste – früh raus bei Verlust
    'RUNNER':      (-50.0, 175.0),  # Alles oder nichts – hoher TP, akzeptiert tiefe Verluste
    'SCALPER':     (-20.0,  40.0),  # Schnelle kleine Gewinne – sehr enger SL
    'LOSS_MAKER':  (-25.0,  50.0),  # Konservativ – schützt Kapital so gut wie möglich
    'MIXED':       (-50.0, 100.0),  # Globale Defaults
    'UNKNOWN':     (-50.0, 100.0),  # Noch kein Label – globale Defaults
}


class WalletTracker:
    """
    Verwaltet die Performance-Datenbank für Wallets.

    Confidence Score:
        - Win Rate:   45% Gewicht
        - Avg P&L:    35% Gewicht (relativ zur Positionsgröße, logarithmisch)
        - Trade Count: 20% Gewicht (sättigt bei 50 Trades)
        - Minimum 5 Trades für echten Score, sonst 0.5 (neutral)

    Strategie-Label (ab 20 sauberen Trades):
        ASYMMETRIC  – große Gewinne, begrenzte Verluste
        RUNNER      – lässt Gewinne laufen, akzeptiert hohe Verluste
        SCALPER     – konstante kleine Gewinne, enge Verluste
        LOSS_MAKER  – überwiegend Verluste
        MIXED       – kein klares Muster
        UNKNOWN     – unter 20 saubere Trades
    """

    MIN_TRADES_FOR_SCORE = 5    # Unter diesem Wert → neutraler Score 0.5
    MIN_TRADES_FOR_LABEL = 20   # Unter diesem Wert → UNKNOWN Label
    
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
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT NOT NULL,
                wallet        TEXT NOT NULL,
                token         TEXT NOT NULL,
                side          TEXT NOT NULL,
                amount        REAL NOT NULL,
                price_eur     REAL NOT NULL,
                value_eur     REAL NOT NULL,
                pnl_eur       REAL,
                pnl_percent   REAL,
                price_missing INTEGER DEFAULT 0,
                timestamp     TEXT NOT NULL
            )
        """)

        # Migration: price_missing Spalte zu bestehenden DBs hinzufügen
        cursor.execute("PRAGMA table_info(wallet_trades)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'price_missing' not in columns:
            cursor.execute("ALTER TABLE wallet_trades ADD COLUMN price_missing INTEGER DEFAULT 0")
            logger.info("[WalletTracker] Migrated: added price_missing column")
        
        # Wallet Stats / Confidence Cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_stats (
                wallet           TEXT PRIMARY KEY,
                total_trades     INTEGER DEFAULT 0,
                winning_trades   INTEGER DEFAULT 0,
                losing_trades    INTEGER DEFAULT 0,
                total_pnl_eur    REAL DEFAULT 0.0,
                avg_pnl_eur      REAL DEFAULT 0.0,
                win_rate         REAL DEFAULT 0.0,
                confidence_score REAL DEFAULT 0.5,
                strategy_label   TEXT DEFAULT 'UNKNOWN',
                last_updated     TEXT NOT NULL
            )
        """)

        # Migration: strategy_label zu bestehenden DBs hinzufügen
        cursor.execute("PRAGMA table_info(wallet_stats)")
        stat_columns = [row['name'] for row in cursor.fetchall()]
        if 'strategy_label' not in stat_columns:
            cursor.execute("ALTER TABLE wallet_stats ADD COLUMN strategy_label TEXT DEFAULT 'UNKNOWN'")
            logger.info("[WalletTracker] Migrated: added strategy_label column")
        
        # Inaktivitäts-Tags pro Wallet
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_inactivity_tags (
                wallet     TEXT PRIMARY KEY,
                tags       INTEGER DEFAULT 0,
                updated    TEXT NOT NULL
            )
        """)

        # Index für schnelle Wallet-Lookups
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
                    price_missing: bool = False) -> None:
        """
        Speichert einen SELL Trade und aktualisiert Wallet-Stats.
        price_missing=True markiert Trades bei denen kein Preis abrufbar war
        und stattdessen mit 0 EUR gerechnet wurde.
        """
        pnl_eur = (price_eur - entry_price_eur) * amount
        pnl_percent = ((price_eur - entry_price_eur) / entry_price_eur * 100) if entry_price_eur > 0 else 0
        
        conn = self._connect()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO wallet_trades 
            (session_id, wallet, token, side, amount, price_eur, value_eur,
             pnl_eur, pnl_percent, price_missing, timestamp)
            VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, wallet, token,
            amount, price_eur, amount * price_eur,
            pnl_eur, pnl_percent,
            1 if price_missing else 0,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        self._recalculate_stats(wallet)
    
    def _recalculate_stats(self, wallet: str):
        """Berechnet Stats und Confidence Score neu aus allen SELL Trades."""
        conn = self._connect()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT pnl_eur, pnl_percent
            FROM wallet_trades
            WHERE wallet = ? AND side = 'SELL' AND pnl_eur IS NOT NULL
        """, (wallet,))
        
        rows = cursor.fetchall()
        
        if not rows:
            conn.close()
            return
        
        total_trades = len(rows)
        winning = [r for r in rows if r['pnl_eur'] > 0]
        losing  = [r for r in rows if r['pnl_eur'] <= 0]
        
        total_pnl  = sum(r['pnl_eur'] for r in rows)
        avg_pnl    = total_pnl / total_trades
        win_rate   = len(winning) / total_trades
        
        if total_trades < self.MIN_TRADES_FOR_SCORE:
            confidence = 0.2
        else:
            import math

            # 1. Win Rate: 0–45 Punkte
            wr_score = win_rate * 0.45

            # 2. Trade Count: 0–20 Punkte, sättigt bei 50 Trades
            count_score = min(total_trades / 50, 1.0) * 0.20

            # 3. Avg P&L Score: 0–35 Punkte, relativ + logarithmisch
            #
            # Basis: Positionsgröße = CAPITAL_PER_WALLET * POSITION_SIZE
            #        = 1000 EUR * 20% = 200 EUR
            # avg_pnl_pct = durchschnittlicher P&L als % des eingesetzten Kapitals
            # Formel: log2(1 + max(avg_pnl_pct, 0) / 25) / log2(21) * 0.20
            #
            # Beispiele:
            #   avg_pnl_pct =   0% → 0.00
            #   avg_pnl_pct = +25% → 0.05
            #   avg_pnl_pct = +50% → 0.08
            #   avg_pnl_pct = +100% → 0.11
            #   avg_pnl_pct = +200% → 0.14
            #   avg_pnl_pct = +500% → 0.18  (praktisch Maximum)
            #
            # Verluste geben 0 Punkte (kein negativer Einfluss – Win Rate bestraft bereits)
            position_size_eur = 200.0  # 1000 EUR * 20%
            avg_pnl_pct = (avg_pnl / position_size_eur) * 100  # z.B. +25 EUR → +12.5%
            avg_pnl_pct_pos = max(avg_pnl_pct, 0.0)            # Verluste → 0
            pnl_score = (math.log2(1 + avg_pnl_pct_pos / 25) / math.log2(21)) * 0.35
            pnl_score = min(pnl_score, 0.35)                   # Hard cap bei 35 Punkten

            confidence = round(wr_score + count_score + pnl_score, 4)
            confidence = max(0.0, min(1.0, confidence))

        # ── Strategie-Label ─────────────────────────────────────────────────
        strategy_label = self._calculate_strategy_label(wallet, conn)

        cursor.execute("""
            INSERT INTO wallet_stats
                (wallet, total_trades, winning_trades, losing_trades,
                 total_pnl_eur, avg_pnl_eur, win_rate, confidence_score,
                 strategy_label, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet) DO UPDATE SET
                total_trades     = excluded.total_trades,
                winning_trades   = excluded.winning_trades,
                losing_trades    = excluded.losing_trades,
                total_pnl_eur    = excluded.total_pnl_eur,
                avg_pnl_eur      = excluded.avg_pnl_eur,
                win_rate         = excluded.win_rate,
                confidence_score = excluded.confidence_score,
                strategy_label   = excluded.strategy_label,
                last_updated     = excluded.last_updated
        """, (
            wallet, total_trades, len(winning), len(losing),
            total_pnl, avg_pnl, win_rate, confidence,
            strategy_label, datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        avg_pnl_pct_display = (avg_pnl / 200.0) * 100
        logger.debug(
            f"[WalletTracker] {wallet[:8]}... → "
            f"confidence={confidence:.2f} | win_rate={win_rate:.0%} | "
            f"trades={total_trades} | avg_pnl={avg_pnl:+.2f} EUR ({avg_pnl_pct_display:+.1f}% of position)"
        )
    
    def _calculate_strategy_label(self, wallet: str, conn) -> str:
        """
        Berechnet das Strategie-Label aus den letzten sauberen Trades.
        Sauber = kein price_missing, kein 0% P&L (Break-Even / kein echter Exit).
        Mindestens 20 saubere Trades erforderlich, sonst UNKNOWN.
        """
        import statistics

        cursor = conn.cursor()
        cursor.execute("""
            SELECT pnl_percent, pnl_eur
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

        pcts  = [t['pnl_percent'] for t in trades]
        wins  = [p for p in pcts if p > 0]
        losses = [p for p in pcts if p < 0]

        win_rate  = len(wins) / len(pcts)
        avg_win   = statistics.mean(wins)   if wins   else 0.0
        avg_loss  = statistics.mean(losses) if losses else 0.0  # negativ

        gross_profit = sum(t['pnl_eur'] for t in trades if t['pnl_eur'] > 0)
        gross_loss   = abs(sum(t['pnl_eur'] for t in trades if t['pnl_eur'] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0

        # ── Klassifizierung ─────────────────────────────────────────────────
        if win_rate < 0.15:
            label = 'LOSS_MAKER'

        elif avg_win > 80 and abs(avg_loss) < 45 and profit_factor >= 1.0:
            # Große Gewinne, begrenzte Verluste – ideal
            label = 'ASYMMETRIC'

        elif avg_win > 80 and abs(avg_loss) >= 45:
            # Große Gewinne UND große Verluste – lässt alles laufen
            label = 'RUNNER'

        elif avg_win <= 50 and abs(avg_loss) <= 25 and win_rate >= 0.50:
            # Kleine regelmäßige Gewinne, enge Verluste
            label = 'SCALPER'

        else:
            label = 'MIXED'

        logger.debug(
            f"[WalletTracker] {wallet[:8]}... strategy={label} "
            f"win_rate={win_rate:.0%} avg_win={avg_win:+.1f}% "
            f"avg_loss={avg_loss:+.1f}% pf={profit_factor:.2f} "
            f"(n={len(trades)})"
        )
        return label

    def get_strategy_label(self, wallet: str) -> str:
        """Gibt das Strategie-Label eines Wallets zurück."""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT strategy_label FROM wallet_stats WHERE wallet = ?",
            (wallet,)
        )
        row = cursor.fetchone()
        conn.close()
        return row['strategy_label'] if row else 'UNKNOWN'

    def get_sl_tp_for_wallet(self, wallet: str) -> tuple:
        """
        Gibt (stop_loss_pct, take_profit_pct) für ein Wallet zurück.
        Basiert auf dem Strategie-Label. Fallback: globale Defaults.
        """
        label = self.get_strategy_label(wallet)
        return STRATEGY_SL_TP.get(label, STRATEGY_SL_TP['UNKNOWN'])

    def get_sl_tp_for_wallets(self, wallets: list) -> tuple:
        """
        Gibt gemittelten (stop_loss_pct, take_profit_pct) für mehrere Wallets.
        Wallets mit UNKNOWN Label werden ignoriert falls andere Labels vorhanden.
        """
        sl_tp_values = []
        for wallet in wallets:
            label = self.get_strategy_label(wallet)
            if label != 'UNKNOWN':
                sl_tp_values.append(STRATEGY_SL_TP[label])

        if not sl_tp_values:
            return STRATEGY_SL_TP['UNKNOWN']

        avg_sl = sum(v[0] for v in sl_tp_values) / len(sl_tp_values)
        avg_tp = sum(v[1] for v in sl_tp_values) / len(sl_tp_values)
        return (round(avg_sl, 1), round(avg_tp, 1))

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
    
    def get_stats(self, wallet: str) -> Optional[WalletStats]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM wallet_stats WHERE wallet = ?", (wallet,)
        )
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
        cursor.execute(
            "SELECT * FROM wallet_stats ORDER BY confidence_score DESC"
        )
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
    
    # ── Inaktivitäts-Tag System ────────────────────────────────────────────

    INACTIVITY_TIMEOUT_DEFAULT = 600   # 10 Minuten in Sekunden
    INACTIVITY_TIMEOUT_PENALIZED = 300  # 5 Minuten bei 3 Tags
    INACTIVITY_MAX_TAGS = 3

    def get_inactivity_timeout(self, wallets: list) -> int:
        """
        Gibt den Inaktivitäts-Timeout für eine Liste von Wallets zurück.
        Wenn mind. ein Wallet 3 Tags hat → 5 Min, sonst 10 Min.
        """
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
        if max_tags >= self.INACTIVITY_MAX_TAGS:
            return self.INACTIVITY_TIMEOUT_PENALIZED
        return self.INACTIVITY_TIMEOUT_DEFAULT

    def add_inactivity_tag(self, wallet: str) -> int:
        """
        Fügt einem Wallet einen Inaktivitäts-Tag hinzu (max 3).
        Gibt die neue Tag-Anzahl zurück.
        """
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
        """
        Baut einen Inaktivitäts-Tag ab (nach erfolgreichem Close).
        Gibt die neue Tag-Anzahl zurück.
        """
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
        if new_tags >= 0:
            logger.info(f"[WalletTracker] {wallet[:8]}... inactivity tag -1 → {new_tags}/{self.INACTIVITY_MAX_TAGS}")
        return new_tags

    def get_inactivity_tags(self, wallet: str) -> int:
        """Gibt die aktuelle Tag-Anzahl eines Wallets zurück."""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT tags FROM wallet_inactivity_tags WHERE wallet = ?", (wallet,))
        row = cursor.fetchone()
        conn.close()
        return row['tags'] if row else 0

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
