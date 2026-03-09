# -*- coding: utf-8 -*-
# Loescht alle Trades aus Sessions vor Einfuehrung des Stop-Loss (02.03.2026)
# und berechnet alle Wallet-Stats neu.
#
# Ausfuehren:
#   cd C:\Users\phili\Documents\GitHub\copybot\bot
#   python cleanup_pre_sl_data.py

import sqlite3
import math
import statistics
from datetime import datetime

DB_PATH = "data/wallet_performance.db"
PRE_SL_CUTOFF = "2026-03-03"

POSITION_SIZE_EUR = 200.0
MIN_TRADES_FOR_SCORE   = 5
MIN_TRADES_FOR_LABEL   = 20
MIN_TRADES_FOR_DYNAMIC = 20


def calc_label(trades):
    clean = [t for t in trades if t['price_missing'] == 0 and t['pnl_percent'] != 0]
    if len(clean) < MIN_TRADES_FOR_LABEL:
        return 'UNKNOWN'
    pcts   = [t['pnl_percent'] for t in clean]
    wins   = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    win_rate     = len(wins) / len(pcts)
    avg_win      = statistics.mean(wins)   if wins   else 0.0
    avg_loss     = statistics.mean(losses) if losses else 0.0
    gross_profit = sum(t['pnl_eur'] for t in clean if t['pnl_eur'] > 0)
    gross_loss   = abs(sum(t['pnl_eur'] for t in clean if t['pnl_eur'] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0
    lows  = [t['min_price_pct'] for t in clean if t['min_price_pct'] is not None]
    highs = [t['max_price_pct'] for t in clean if t['max_price_pct'] is not None]
    med_dd   = statistics.median(lows)  if lows  else avg_loss
    med_high = statistics.median(highs) if highs else avg_win

    if win_rate < 0.15:
        return 'LOSS_MAKER'
    if avg_win > 80 and abs(avg_loss) < 45 and profit_factor >= 1.0:
        return 'ASYMMETRIC'
    if avg_win > 60 and abs(avg_loss) >= 35:
        if lows and highs:
            if med_high > avg_win * 0.8 and abs(med_dd) > 30:
                return 'RUNNER'
            if abs(med_dd) <= 30:
                return 'MIXED'
        return 'RUNNER'
    if avg_win <= 50 and abs(avg_loss) <= 25 and win_rate >= 0.50:
        if lows:
            return 'SCALPER' if abs(med_dd) <= 35 else 'MIXED'
        return 'SCALPER'
    return 'MIXED'


def calc_sl_tp(trades):
    clean = [t for t in trades if t['price_missing'] == 0 and t['pnl_percent'] != 0]
    if len(clean) < MIN_TRADES_FOR_DYNAMIC:
        return (None, None)
    pcts   = [t['pnl_percent'] for t in clean]
    wins   = sorted([p for p in pcts if p > 0])
    losses = sorted([p for p in pcts if p < 0])
    dyn_tp = round(max(20.0, min(300.0, wins[max(0, int(len(wins)*0.25)-1)])), 1) if wins else None
    lows   = sorted([t['min_price_pct'] for t in clean if t['min_price_pct'] is not None])
    if lows:
        sl_idx = min(len(lows)-1, int(len(lows)*0.75))
        dyn_sl = round(max(-80.0, min(-10.0, lows[sl_idx]*1.1)), 1)
    elif losses:
        sl_idx = min(len(losses)-1, int(len(losses)*0.75))
        dyn_sl = round(max(-80.0, min(-10.0, losses[sl_idx])), 1)
    else:
        dyn_sl = None
    return (dyn_sl, dyn_tp)


def main():
    print()
    print("=" * 70)
    print("CLEANUP: PRE-SL DATEN LOESCHEN")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Zeige was geloescht wird
    c.execute("""
        SELECT session_id, COUNT(*) as trades,
               MIN(timestamp) as started,
               COUNT(CASE WHEN pnl_percent < -80 AND side='SELL' THEN 1 END) as catastrophic
        FROM wallet_trades
        WHERE timestamp < ?
        GROUP BY session_id
        ORDER BY started
    """, (PRE_SL_CUTOFF,))
    sessions = c.fetchall()

    if not sessions:
        print("  Keine Pre-SL Daten gefunden - nichts zu tun.")
        conn.close()
        return

    print("\nFolgende Sessions werden geloescht (vor " + PRE_SL_CUTOFF + "):\n")
    total_trades = 0
    for s in sessions:
        print("  [DEL]  " + s['session_id'] + "  (" + str(s['trades']) + " Trades, Start: " + s['started'][:16] + ", Katastrophal: " + str(s['catastrophic']) + ")")
        total_trades += s['trades']

    print("\n  Gesamt: " + str(total_trades) + " Trades in " + str(len(sessions)) + " Sessions\n")

    confirm = input("Loeschen bestaetigen? (ja/nein): ").strip().lower()
    if confirm != "ja":
        print("\n  Abgebrochen.\n")
        conn.close()
        return

    # Trades loeschen
    c.execute("DELETE FROM wallet_trades WHERE timestamp < ?", (PRE_SL_CUTOFF,))
    deleted = c.rowcount
    print("\n  OK: " + str(deleted) + " Trades geloescht")

    # Stats neu berechnen
    print("\nStats werden neu berechnet...\n")
    c.execute("SELECT DISTINCT wallet FROM wallet_trades WHERE side='SELL'")
    wallets = [r['wallet'] for r in c.fetchall()]

    print("  " + "Wallet".ljust(22) + "T".rjust(5) + "WR%".rjust(6) + "Conf".rjust(6) + "Label".ljust(14) + "dyn_SL".rjust(8) + "dyn_TP".rjust(8))
    print("  " + "-" * 68)

    for wallet in wallets:
        c.execute("""
            SELECT pnl_eur, pnl_percent, price_missing, min_price_pct, max_price_pct
            FROM wallet_trades WHERE wallet=? AND side='SELL' AND pnl_eur IS NOT NULL
        """, (wallet,))
        trades = [dict(r) for r in c.fetchall()]
        if not trades:
            continue

        total     = len(trades)
        wins_list = [t for t in trades if t['pnl_eur'] > 0]
        total_pnl = sum(t['pnl_eur'] for t in trades)
        avg_pnl   = total_pnl / total
        win_rate  = len(wins_list) / total

        if total < MIN_TRADES_FOR_SCORE:
            conf = 0.2
        else:
            wr_s = win_rate * 0.45
            c_s  = min(total / 50, 1.0) * 0.20
            p_s  = min((math.log2(1 + max((avg_pnl / POSITION_SIZE_EUR) * 100, 0) / 25) / math.log2(21)) * 0.35, 0.35)
            conf = round(max(0.0, min(1.0, wr_s + c_s + p_s)), 4)

        label          = calc_label(trades)
        dyn_sl, dyn_tp = calc_sl_tp(trades)

        c.execute("""
            INSERT INTO wallet_stats
                (wallet, total_trades, winning_trades, losing_trades,
                 total_pnl_eur, avg_pnl_eur, win_rate, confidence_score,
                 strategy_label, dynamic_sl, dynamic_tp, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
        """, (wallet, total, len(wins_list), total - len(wins_list),
              total_pnl, avg_pnl, win_rate, conf,
              label, dyn_sl, dyn_tp, datetime.now().isoformat()))

        sl_str = str(round(dyn_sl)) + "%" if dyn_sl else "  --"
        tp_str = "+" + str(round(dyn_tp)) + "%" if dyn_tp else "  --"
        print("  " + wallet[:22].ljust(22) + str(total).rjust(5) + (str(round(win_rate*100)) + "%").rjust(6) + str(conf).rjust(6) + label.ljust(14) + sl_str.rjust(8) + tp_str.rjust(8))

    # Wallets ohne verbleibende Trades entfernen
    c.execute("""
        DELETE FROM wallet_stats
        WHERE wallet NOT IN (
            SELECT DISTINCT wallet FROM wallet_trades WHERE side='SELL'
        )
    """)
    removed = c.rowcount
    if removed:
        print("\n  OK: " + str(removed) + " Wallet(s) ohne verbleibende Trades entfernt")

    conn.commit()
    conn.close()

    print()
    print("=" * 70)
    print("Fertig - DB bereinigt und Stats aktualisiert")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
