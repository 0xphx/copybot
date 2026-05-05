"""
Einmaliges Script: Berechnet Confidence Scores aller Wallets neu.
Nutzt die neue Formel aus wallet_tracker.py.

Aufruf: python recalc_confidence.py
        python recalc_confidence.py --analysis   (Analysis-DB statt Observer)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from trading.wallet_tracker import WalletTracker

def recalc(db_path: str, observer_mode: bool):
    tracker = WalletTracker(db_path=db_path, observer_mode=observer_mode)
    conn    = tracker._connect()
    wallets = [r[0] for r in conn.execute(
        "SELECT DISTINCT wallet FROM wallet_trades WHERE side='SELL'"
    ).fetchall()]
    conn.close()

    print(f"[Recalc] {len(wallets)} Wallets in {db_path}")
    print(f"[Recalc] Neue Formel: (WinRate×0.55 + tanh(AvgPnL/50)×0.45) × min(n/100, 1.0)")
    print()

    for i, wallet in enumerate(wallets):
        old_score = tracker.get_confidence(wallet)
        tracker._recalculate_stats(wallet)
        new_score = tracker.get_confidence(wallet)
        diff  = new_score - old_score
        arrow = "↑" if diff > 0.001 else "↓" if diff < -0.001 else "="
        print(f"  [{i+1:>3}/{len(wallets)}] {wallet[:20]}...  {old_score:.4f} → {new_score:.4f}  {arrow} {diff:+.4f}")

    print()
    print(f"[Recalc] Fertig. {len(wallets)} Wallets aktualisiert.")

if __name__ == "__main__":
    use_analysis = "--analysis" in sys.argv
    db_path      = "data/wallet_performance.db" if use_analysis else "data/observer_performance.db"
    recalc(db_path, observer_mode=not use_analysis)
