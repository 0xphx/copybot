"""
evaluate_wallets.py - Vergleicht CandidateWallets mit ActiveWallets anhand von EV

EV (Expected Value) = WinRate * AvgWin - (1 - WinRate) * AvgLoss

Ablauf:
  1. Berechne EV fuer alle Active + Candidate Wallets aus observer_performance.db
  2. Zeige Vergleich: welche Candidates schlagen welche Actives
  3. Frage zur Bestaetigung vor dem Austausch
  4. Austausch: schlechteste Active -> ArchivedWallet, Candidate -> ActiveWallet

Bedingungen fuer Vergleich:
  - Mindestens 20 saubere Trades (ohne SESSION_ENDED, CRASH_RECOVERY)
  - Nur Candidates mit hoeherem EV als mindestens ein Active

Archivierung:
  - Ersetzte Active-Wallets werden als ArchivedWallet markiert (label bleibt erhalten)
  - Candidates die befoerdert werden, behalten ihr Label aus der DB
"""

import sqlite3
from pathlib import Path

AXIOM_DB     = Path(__file__).parent.parent / "data" / "axiom.db"
OBSERVER_DB  = Path(__file__).parent.parent / "data" / "observer_performance.db"
MIN_TRADES   = 20
EXCLUDED_REASONS = ("SESSION_ENDED", "CRASH_RECOVERY")


def calc_ev(wallet: str, conn_obs) -> dict | None:
    """
    Berechnet EV fuer ein Wallet aus der Observer-DB.
    Gibt None zurueck wenn zu wenig Trades vorhanden.
    """
    sells = conn_obs.execute("""
        SELECT pnl_eur FROM wallet_trades
        WHERE wallet = ? AND side = 'SELL'
          AND reason NOT IN ('SESSION_ENDED', 'CRASH_RECOVERY')
          AND price_missing = 0
    """, (wallet,)).fetchall()

    if len(sells) < MIN_TRADES:
        return None

    pnls  = [row[0] for row in sells if row[0] is not None]
    wins  = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win  = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0

    ev = win_rate * avg_win - (1 - win_rate) * avg_loss

    return {
        "wallet":    wallet,
        "trades":    len(pnls),
        "win_rate":  win_rate,
        "avg_win":   avg_win,
        "avg_loss":  avg_loss,
        "ev":        ev,
    }


def run():
    if not AXIOM_DB.exists():
        print(f"\n[Fehler] axiom.db nicht gefunden: {AXIOM_DB}")
        return

    if not OBSERVER_DB.exists():
        print(f"\n[Fehler] observer_performance.db nicht gefunden: {OBSERVER_DB}")
        print("  Tipp: Observer Mode mindestens einmal ausfuehren.\n")
        return

    conn_ax  = sqlite3.connect(str(AXIOM_DB))
    conn_obs = sqlite3.connect(str(OBSERVER_DB))

    # Aktive und Candidate Wallets laden
    actives = conn_ax.execute("""
        SELECT wallet, COALESCE(source, '') FROM axiom_wallets
        WHERE category = 'ActiveWallet' AND active = 1
    """).fetchall()

    candidates = conn_ax.execute("""
        SELECT wallet, COALESCE(source, '') FROM axiom_wallets
        WHERE category = 'CandidateWallet' AND active = 1
    """).fetchall()

    conn_ax.close()

    if not candidates:
        print("\n[Hinweis] Keine CandidateWallets in der DB.")
        print("  Tipp: Neue Wallets mit category='CandidateWallet' in axiom_wallets.json eintragen")
        print("  und python import_wallets.py ausfuehren.\n")
        conn_obs.close()
        return

    # EV berechnen
    print()
    print("=" * 70)
    print("  WALLET EVALUATION  (EV-basierter Vergleich)")
    print("=" * 70)
    print(f"  Mindest-Trades: {MIN_TRADES}  |  Basis: observer_performance.db")
    print()

    active_evs    = []
    candidate_evs = []

    print(f"  {'ACTIVE WALLETS':<25} {'T':>4}  {'WR':>6}  {'AvgWin':>9}  {'AvgLoss':>9}  {'EV':>9}")
    print("  " + "-" * 68)
    for wallet, label in actives:
        result = calc_ev(wallet, conn_obs)
        label_str = f" [{label}]" if label else ""
        if result:
            active_evs.append(result)
            print(
                f"  {wallet[:20]}...{label_str:<8}"
                f" {result['trades']:>4}"
                f"  {result['win_rate']*100:>5.0f}%"
                f"  {result['avg_win']:>+9.2f}"
                f"  {result['avg_loss']:>9.2f}"
                f"  {result['ev']:>+9.2f}"
            )
        else:
            trades = conn_obs.execute(
                "SELECT COUNT(*) FROM wallet_trades WHERE wallet=? AND side='SELL' AND reason NOT IN ('SESSION_ENDED','CRASH_RECOVERY')",
                (wallet,)
            ).fetchone()[0]
            print(f"  {wallet[:20]}...{label_str:<8} {'':>4}  {'':>6}  {'':>9}  {'':>9}  [zu wenig Daten: {trades}/{MIN_TRADES}]")

    print()
    print(f"  {'CANDIDATE WALLETS':<25} {'T':>4}  {'WR':>6}  {'AvgWin':>9}  {'AvgLoss':>9}  {'EV':>9}")
    print("  " + "-" * 68)
    for wallet, label in candidates:
        result = calc_ev(wallet, conn_obs)
        label_str = f" [{label}]" if label else ""
        if result:
            candidate_evs.append(result)
            print(
                f"  {wallet[:20]}...{label_str:<8}"
                f" {result['trades']:>4}"
                f"  {result['win_rate']*100:>5.0f}%"
                f"  {result['avg_win']:>+9.2f}"
                f"  {result['avg_loss']:>9.2f}"
                f"  {result['ev']:>+9.2f}"
            )
        else:
            trades = conn_obs.execute(
                "SELECT COUNT(*) FROM wallet_trades WHERE wallet=? AND side='SELL' AND reason NOT IN ('SESSION_ENDED','CRASH_RECOVERY')",
                (wallet,)
            ).fetchone()[0]
            print(f"  {wallet[:20]}...{label_str:<8} {'':>4}  {'':>6}  {'':>9}  {'':>9}  [zu wenig Daten: {trades}/{MIN_TRADES}]")

    conn_obs.close()

    if not active_evs:
        print("\n[Hinweis] Keine Active Wallets mit genuegend Trades fuer Vergleich.")
        print(f"  Mind. {MIN_TRADES} saubere Trades pro Wallet benoetigt.\n")
        return

    if not candidate_evs:
        print("\n[Hinweis] Keine Candidate Wallets mit genuegend Trades fuer Vergleich.")
        print(f"  Mind. {MIN_TRADES} saubere Trades pro Wallet benoetigt.\n")
        return

    # Vorschlaege: Candidates die schlechteste Actives schlagen
    active_evs_sorted    = sorted(active_evs,    key=lambda x: x['ev'])
    candidate_evs_sorted = sorted(candidate_evs, key=lambda x: x['ev'], reverse=True)

    swaps = []  # (candidate, active_to_replace)
    replaced_actives = set()

    for candidate in candidate_evs_sorted:
        for active in active_evs_sorted:
            if active['wallet'] in replaced_actives:
                continue
            if candidate['ev'] > active['ev']:
                swaps.append((candidate, active))
                replaced_actives.add(active['wallet'])
                break  # jeder Candidate ersetzt max. einen Active

    if not swaps:
        print()
        print("  Kein Candidate schlaegt einen Active Wallet.")
        print("  Alle Active Wallets sind bereits besser als die Candidates.\n")
        return

    # Vorschlaege anzeigen
    print()
    print("=" * 70)
    print(f"  AUSTAUSCH-VORSCHLAEGE ({len(swaps)} Tausch{'e' if len(swaps) != 1 else ''})")
    print("=" * 70)
    for i, (cand, active) in enumerate(swaps, 1):
        diff = cand['ev'] - active['ev']
        print(f"\n  [{i}] CANDIDATE  {cand['wallet'][:20]}...  EV={cand['ev']:+.2f}  (WR={cand['win_rate']*100:.0f}%, {cand['trades']}T)")
        print(f"       ersetzt ACTIVE   {active['wallet'][:20]}...  EV={active['ev']:+.2f}  (WR={active['win_rate']*100:.0f}%, {active['trades']}T)")
        print(f"       EV-Vorteil: {diff:+.2f} EUR pro Trade")

    print()
    print("=" * 70)
    print("  Active -> ArchivedWallet  |  Candidate -> ActiveWallet")
    print("=" * 70)
    print()

    # Bestaetigung
    while True:
        inp = input("  Alle Tausche durchfuehren? [j/n]: ").strip().lower()
        if inp in ("j", "ja", "y", "yes"):
            break
        elif inp in ("n", "nein", "no"):
            print("\n  Abgebrochen. Keine Aenderungen vorgenommen.\n")
            return
        else:
            print("  Bitte 'j' oder 'n' eingeben.")

    # Austausch in axiom_wallets.json durchfuehren
    import json, shutil
    json_path = Path(__file__).parent.parent / "data" / "axiom_wallets.json"
    bak_path  = json_path.with_suffix(".json.bak")
    shutil.copy(json_path, bak_path)

    with open(json_path, "r", encoding="utf-8") as f:
        wallet_list = json.load(f)

    to_archive  = {active['wallet'] for _, active in swaps}
    to_activate = {cand['wallet'] for cand, _ in swaps}

    # Label-Mapping: Candidate-Wallet behaelt sein bestehendes label, bekommt aber ActiveWallet-Kategorie
    for entry in wallet_list:
        if entry["wallet"] in to_archive:
            entry["category"] = "ArchivedWallet"
        elif entry["wallet"] in to_activate:
            entry["category"] = "ActiveWallet"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(wallet_list, f, indent=4, ensure_ascii=False)

    print()
    print(f"  axiom_wallets.json aktualisiert (Backup: axiom_wallets.json.bak)")
    print()
    for cand, active in swaps:
        print(f"  OK  {active['wallet'][:20]}... -> ArchivedWallet")
        print(f"  OK  {cand['wallet'][:20]}...  -> ActiveWallet")
    print()
    print("  Jetzt ausfuehren: python import_wallets.py")
    print()
