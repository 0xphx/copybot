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


class WalletTracker:
    """
    Verwaltet die Performance-Datenbank für Wallets.
    
    Confidence Score Formel:
        - Basis: Win Rate (0–60 Punkte)
        - Bonus: Trade Count (bis zu 20 Punkte, mehr Daten = sicherer)
        - Bonus: Avg P&L positiv (bis zu 20 Punkte)
        - Minimum 5 Trades für echten Score, sonst 0.5 (neutral)
    """
    
    MIN_TRADES_FOR_SCORE = 5   # Unter diesem Wert → neutraler Score 0.5
    
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
                wallet          TEXT PRIMARY KEY,
                total_trades    INTEGER DEFAULT 0,
                winning_trades  INTEGER DEFAULT 0,
                losing_trades   INTEGER DEFAULT 0,
                total_pnl_eur   REAL DEFAULT 0.0,
                avg_pnl_eur     REAL DEFAULT 0.0,
                win_rate        REAL DEFAULT 0.0,
                confidence_score REAL DEFAULT 0.5,
                last_updated    TEXT NOT NULL
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
            confidence = 0.5
        else:
            wr_score = win_rate * 0.60
            count_score = min(total_trades / 50, 1.0) * 0.20
            avg_pnl_clamped = max(-50, min(50, avg_pnl))
            pnl_score = ((avg_pnl_clamped + 50) / 100) * 0.20
            confidence = round(wr_score + count_score + pnl_score, 4)
            confidence = max(0.0, min(1.0, confidence))
        
        cursor.execute("""
            INSERT INTO wallet_stats 
                (wallet, total_trades, winning_trades, losing_trades,
                 total_pnl_eur, avg_pnl_eur, win_rate, confidence_score, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet) DO UPDATE SET
                total_trades    = excluded.total_trades,
                winning_trades  = excluded.winning_trades,
                losing_trades   = excluded.losing_trades,
                total_pnl_eur   = excluded.total_pnl_eur,
                avg_pnl_eur     = excluded.avg_pnl_eur,
                win_rate        = excluded.win_rate,
                confidence_score = excluded.confidence_score,
                last_updated    = excluded.last_updated
        """, (
            wallet, total_trades, len(winning), len(losing),
            total_pnl, avg_pnl, win_rate, confidence,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        logger.debug(
            f"[WalletTracker] {wallet[:8]}... → "
            f"confidence={confidence:.2f} | win_rate={win_rate:.0%} | "
            f"trades={total_trades} | avg_pnl={avg_pnl:+.2f} EUR"
        )
    
    def get_confidence(self, wallet: str) -> float:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT confidence_score FROM wallet_stats WHERE wallet = ?",
            (wallet,)
        )
        row = cursor.fetchone()
        conn.close()
        return row['confidence_score'] if row else 0.5
    
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
        
        result = {w: 0.5 for w in wallets}
        for row in rows:
            result[row['wallet']] = row['confidence_score']
        return result
