"""
Einmalig ausführen: Migriert DB-Schema und berechnet alle Stats neu
mit der neuen Label-Logik (High/Low-basiert) + dynamischen SL/TP.

cd C:\Users\phili\Documents\GitHub\copybot\bot
python migrate_and_recalc.py
"""
import sqlite3, math, statistics, sys
from datetime import datetime

DB_PATH = "data/wallet_performance.db"
POSITION_SIZE_EUR = 200.0

def migrate(conn):
    c = conn.cursor()
    c.execute("PRAGMA table_info(wallet_trades)")
    trade_cols = [r[1] for r in c.fetchall()]
    for col, typedef in [('price_missing','INTEGER DEFAULT 0'),('max_price_pct','REAL'),('min_price_pct','REAL')]:
        if col not in trade_cols:
            c.execute(f"ALTER TABLE wallet_trades ADD COLUMN {col} {typedef}")
            print(f"  Migrated wallet_trades: +{col}")
    c.execute("PRAGMA table_info(wallet_stats)")
    stat_cols = [r[1] for r in c.fetchall()]
    for col, typedef in [("strategy_label","TEXT DEFAULT 'UNKNOWN'"),('dynamic_sl','REAL'),('dynamic_tp','REAL')]:
        if col not in stat_cols:
            c.execute(f"ALTER TABLE wallet_stats ADD COLUMN {col} {typedef}")
            print(f"  Migrated wallet_stats: +{col}")
    conn.commit()

def calc_label(trades):
    clean = [t for t in trades if t[2] == 0 and t[1] != 0]  # price_missing=0, pnl_percent!=0
    if len(clean) < 20:
        return 'UNKNOWN'
    pcts   = [t[1] for t in clean]   # pnl_percent
    wins   = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    win_rate  = len(wins) / len(pcts)
    avg_win   = statistics.mean(wins)   if wins   else 0.0
    avg_loss  = statistics.mean(losses) if losses else 0.0
    gross_profit = sum(t[0] for t in clean if t[0] > 0)   # pnl_eur
    gross_loss   = abs(sum(t[0] for t in clean if t[0] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0
    lows  = [t[3] for t in clean if t[3] is not None]   # min_price_pct
    highs = [t[4] for t in clean if t[4] is not None]   # max_price_pct
    med_dd   = statistics.median(lows)  if lows  else avg_loss
    med_high = statistics.median(highs) if highs else avg_win

    if win_rate < 0.15: return 'LOSS_MAKER'
    if avg_win > 80 and abs(avg_loss) < 45 and profit_factor >= 1.0: return 'ASYMMETRIC'
    if avg_win > 60 and abs(avg_loss) >= 35:
        if lows and highs:
            if med_high > avg_win * 0.8 and abs(med_dd) > 30: return 'RUNNER'
            if abs(med_dd) <= 30: return 'MIXED'
        return 'RUNNER'
    if avg_win <= 50 and abs(avg_loss) <= 25 and win_rate >= 0.50:
        if lows: return 'SCALPER' if abs(med_dd) <= 35 else 'MIXED'
        return 'SCALPER'
    return 'MIXED'

def calc_sl_tp(trades):
    # trades: (pnl_eur, pnl_percent, price_missing, min_price_pct, max_price_pct)
    clean = [t for t in trades if t[2] == 0 and t[1] != 0]
    if len(clean) < 20: return (None, None)
    pcts   = [t[1] for t in clean]
    wins   = sorted([p for p in pcts if p > 0])
    losses = sorted([p for p in pcts if p < 0])
    dyn_tp = round(max(20.0, min(300.0, wins[max(0, int(len(wins)*0.25)-1)])), 1) if wins else None
    lows   = sorted([t[3] for t in clean if t[3] is not None])
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
    print(f"\n{'='*70}")
    print("DB MIGRATION & STATS NEUBERECHNUNG")
    print(f"{'='*70}\n")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("Schema-Migration...")
    migrate(conn)
    print("  OK\n")

    cursor.execute("SELECT DISTINCT wallet FROM wallet_trades WHERE side='SELL'")
    wallets = [r[0] for r in cursor.fetchall()]

    print(f"{'Wallet':<22} {'T':>4} {'WR%':>5} {'Conf':>5} {'Label':<12} {'dyn_SL':>7} {'dyn_TP':>7}  High/Low")
    print("-"*80)

    for wallet in wallets:
        cursor.execute("""
            SELECT pnl_eur, pnl_percent, price_missing, min_price_pct, max_price_pct
            FROM wallet_trades WHERE wallet=? AND side='SELL' AND pnl_eur IS NOT NULL
        """, (wallet,))
        trades = cursor.fetchall()
        if not trades: continue

        total     = len(trades)
        wins_list = [t for t in trades if t[0] > 0]
        total_pnl = sum(t[0] for t in trades)
        avg_pnl   = total_pnl / total
        win_rate  = len(wins_list) / total

        if total < 5:
            conf = 0.2
        else:
            wr_s = win_rate * 0.45
            c_s  = min(total/50,1.0)*0.20
            p_s  = min((math.log2(1+max((avg_pnl/POSITION_SIZE_EUR)*100,0)/25)/math.log2(21))*0.35, 0.35)
            conf = round(max(0.0, min(1.0, wr_s+c_s+p_s)), 4)

        label          = calc_label(trades)
        dyn_sl, dyn_tp = calc_sl_tp(trades)
        n_lows  = sum(1 for t in trades if t[3] is not None)
        n_highs = sum(1 for t in trades if t[4] is not None)

        cursor.execute("""
            INSERT INTO wallet_stats
                (wallet,total_trades,winning_trades,losing_trades,total_pnl_eur,avg_pnl_eur,
                 win_rate,confidence_score,strategy_label,dynamic_sl,dynamic_tp,last_updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(wallet) DO UPDATE SET
                total_trades=excluded.total_trades,winning_trades=excluded.winning_trades,
                losing_trades=excluded.losing_trades,total_pnl_eur=excluded.total_pnl_eur,
                avg_pnl_eur=excluded.avg_pnl_eur,win_rate=excluded.win_rate,
                confidence_score=excluded.confidence_score,strategy_label=excluded.strategy_label,
                dynamic_sl=excluded.dynamic_sl,dynamic_tp=excluded.dynamic_tp,
                last_updated=excluded.last_updated
        """, (wallet,total,len(wins_list),total-len(wins_list),total_pnl,avg_pnl,
              win_rate,conf,label,dyn_sl,dyn_tp,datetime.now().isoformat()))

        sl_str = f"{dyn_sl:.0f}%" if dyn_sl else "  --"
        tp_str = f"+{dyn_tp:.0f}%" if dyn_tp else "  --"
        hl_str = f"lows={n_lows}/{total} highs={n_highs}/{total}"
        print(f"{wallet[:22]:<22} {total:>4} {win_rate*100:>4.0f}% {conf:>5.3f} {label:<12} {sl_str:>7} {tp_str:>7}  {hl_str}")

    conn.commit()
    conn.close()

    print(f"\n{'='*70}")
    print("✅ Fertig – Stats aktualisiert")
    print()
    print("Hinweis: dyn_SL/TP basieren noch auf Verlust-Exits (keine lows/highs in DB).")
    print("Ab der nächsten Analyse-Session werden echte High/Low Werte getrackt.")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
