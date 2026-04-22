"""
tune_observer.py - Hyperparameter-Simulator fuer den Observer-Modus

Simuliert alle Kombinationen von Stagnation-Timeout und Max-Hold-Timeout
auf den bereits vorhandenen Observer-Daten und findet die optimale Konfiguration.

Wie es funktioniert:
  - Laedt alle Trades aus observer_performance.db
  - Rekonstruiert den Preisverlauf jeder Position aus den gespeicherten Daten
  - Simuliert fuer jede Parameter-Kombination wann eine Position geschlossen
    worden waere und berechnet den resultierenden PnL
  - Gibt eine Ranking-Tabelle aller Kombinationen aus

Aufruf:
  python main.py tune_observer
  python main.py tune_observer --sessions 3     # nur letzte 3 Sessions
  python main.py tune_observer --top 5          # zeige Top 5 Kombinationen
"""

import sqlite3
import sys
from pathlib import Path
from itertools import product
from collections import defaultdict
from datetime import datetime

DB_PATH = Path("data/observer_performance.db")

# Parameter-Raster
STAGNATION_VALUES = [5, 10, 15, 20, 30]   # Minuten
MAX_HOLD_VALUES   = [20, 40, 60, 90, 120]  # Minuten

EXCLUDED_REASONS  = ("SESSION_ENDED", "CRASH_RECOVERY")


def load_positions(conn, session_filter: list = None) -> list:
    """
    Laedt alle geschlossenen Positionen mit ihren Preis-Zeitstempeln.
    Gibt eine Liste von Position-Dicts zurueck.

    Jede Position enthaelt:
      - wallet, token, session_id
      - entry_time, entry_price
      - exit_time, exit_price, exit_reason
      - price_history: Liste von (timestamp_iso, price_eur) aus dem Preisverlauf
        (rekonstruiert aus den gespeicherten max/min und dem tatsaechlichen Exit)
    """
    # Filter aufbauen
    session_clause = ""
    params = []
    if session_filter:
        placeholders = ",".join("?" * len(session_filter))
        session_clause = f"AND b.session_id IN ({placeholders})"
        params = session_filter

    rows = conn.execute(f"""
        SELECT
            b.wallet, b.token, b.session_id,
            b.timestamp   as entry_time,
            b.price_eur   as entry_price,
            s.timestamp   as exit_time,
            s.price_eur   as exit_price,
            s.pnl_eur     as pnl_eur,
            s.pnl_percent as pnl_percent,
            s.reason      as exit_reason,
            s.max_price_pct as max_price_pct,
            s.min_price_pct as min_price_pct,
            s.price_missing as price_missing
        FROM wallet_trades b
        JOIN wallet_trades s
            ON b.wallet = s.wallet
            AND b.token  = s.token
            AND b.session_id = s.session_id
            AND b.side = 'BUY'
            AND s.side = 'SELL'
        WHERE s.reason NOT IN ({','.join('?' * len(EXCLUDED_REASONS))})
          AND s.price_missing = 0
          {session_clause}
        ORDER BY b.timestamp
    """, list(EXCLUDED_REASONS) + params).fetchall()

    positions = []
    for r in rows:
        try:
            entry_dt = datetime.fromisoformat(r[3])
            exit_dt  = datetime.fromisoformat(r[5])
            hold_min = (exit_dt - entry_dt).total_seconds() / 60
        except Exception:
            continue

        positions.append({
            "wallet":        r[0],
            "token":         r[1],
            "session_id":    r[2],
            "entry_time":    r[3],
            "entry_price":   r[4],
            "exit_time":     r[5],
            "exit_price":    r[6],
            "pnl_eur":       r[7],
            "pnl_percent":   r[8],
            "exit_reason":   r[9],
            "max_price_pct": r[10],
            "min_price_pct": r[11],
            "hold_min":      hold_min,
        })

    return positions


def simulate_position(pos: dict, stagnation_min: int, max_hold_min: int) -> dict:
    """
    Simuliert wie eine Position mit den gegebenen Parametern geschlossen worden waere.

    Methode:
    - Wenn hold_min <= min(stag, hold): kein Timeout -> echtes Ergebnis
    - Wenn beide Timeouts ueberschritten: frueherer Timeout gewinnt
    - Lineaire PnL-Interpolation basierend auf dem Anteil der Haltezeit
    """
    h   = pos["hold_min"]
    ep  = pos["entry_price"]
    xp  = pos["exit_price"]
    pnl = pos["pnl_eur"]
    pct = pos["pnl_percent"]

    # Fruehesten Timeout bestimmen
    cutoff = None
    reason = None
    if h > stagnation_min and h > max_hold_min:
        cutoff = min(stagnation_min, max_hold_min)
        reason = "SIM_STAGNATION" if stagnation_min <= max_hold_min else "SIM_MAX_HOLD"
    elif h > max_hold_min:
        cutoff = max_hold_min
        reason = "SIM_MAX_HOLD"
    elif h > stagnation_min:
        cutoff = stagnation_min
        reason = "SIM_STAGNATION"

    if cutoff is not None:
        frac    = cutoff / h if h > 0 else 1.0
        sim_pct = (xp / ep - 1) * 100 * frac if ep > 0 else 0.0
        sim_pnl = pnl * frac
        return {"pnl_eur": sim_pnl, "pnl_pct": sim_pct, "reason": reason}

    return {"pnl_eur": pnl, "pnl_pct": pct, "reason": pos["exit_reason"]}


def run_simulation(positions: list) -> dict:
    """
    Laeuft alle Parameter-Kombinationen durch.
    Gibt Dict (stag, hold) -> Stats zurueck.
    """
    results = {}

    for stag, hold in product(STAGNATION_VALUES, MAX_HOLD_VALUES):
        trades = []
        for pos in positions:
            sim = simulate_position(pos, stag, hold)
            trades.append(sim)

        if not trades:
            continue

        wins   = [t for t in trades if t["pnl_eur"] > 0]
        losses = [t for t in trades if t["pnl_eur"] <= 0]
        total_pnl = sum(t["pnl_eur"] for t in trades)
        win_rate  = len(wins) / len(trades) if trades else 0

        avg_win  = sum(t["pnl_pct"] for t in wins)  / len(wins)  if wins  else 0
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
        ev       = win_rate * avg_win + (1 - win_rate) * avg_loss

        # Exit-Grund Verteilung
        reason_counts = defaultdict(int)
        for t in trades:
            reason_counts[t["reason"]] += 1

        results[(stag, hold)] = {
            "stag":    stag,
            "hold":    hold,
            "n":       len(trades),
            "wins":    len(wins),
            "losses":  len(losses),
            "wr":      win_rate,
            "pnl":     total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "ev":       ev,
            "reasons":  dict(reason_counts),
        }

    return results


def print_results(results: dict, top_n: int = 10):
    """Gibt die Ergebnisse sortiert nach EV aus."""

    sorted_results = sorted(results.values(), key=lambda x: x["ev"], reverse=True)

    print()
    print("=" * 90)
    print(" HYPERPARAMETER SIMULATION - ERGEBNISSE")
    print(f" {len(results)} Kombinationen getestet | sortiert nach EV (Expected Value)")
    print("=" * 90)
    print()
    print(f"  {'Stag':>5} {'Hold':>5}  {'T':>5}  {'WR':>6}  {'AvgWin':>8}  {'AvgLoss':>9}  {'EV':>7}  {'PnL EUR':>10}")
    print("  " + "-" * 70)

    for i, r in enumerate(sorted_results):
        marker = " *" if i == 0 else "  "
        print(
            f"{marker} {r['stag']:>4}m {r['hold']:>4}m"
            f"  {r['n']:>5}"
            f"  {r['wr']*100:>5.0f}%"
            f"  {r['avg_win']:>+7.0f}%"
            f"  {r['avg_loss']:>+8.0f}%"
            f"  {r['ev']:>+6.0f}%"
            f"  {r['pnl']:>+9.0f}"
        )
        if i >= top_n - 1:
            break

    print()
    best = sorted_results[0]
    worst = sorted_results[-1]
    current = results.get((15, 60))

    print("=" * 90)
    print(f"  BESTE  Kombination: Stagnation={best['stag']}min  MaxHold={best['hold']}min")
    print(f"    -> EV={best['ev']:+.0f}%  WR={best['wr']*100:.0f}%  PnL={best['pnl']:+.0f} EUR")
    if current:
        print()
        print(f"  AKTUELLE Konfiguration (15min / 60min):")
        print(f"    -> EV={current['ev']:+.0f}%  WR={current['wr']*100:.0f}%  PnL={current['pnl']:+.0f} EUR")
        diff_pnl = best['pnl'] - current['pnl']
        diff_ev  = best['ev']  - current['ev']
        print(f"  VERBESSERUNG durch Optimierung: {diff_pnl:+.0f} EUR  ({diff_ev:+.0f}% EV)")
    print("=" * 90)

    # Heatmap EV
    print()
    print("  EV HEATMAP (Zeilen=Stagnation, Spalten=MaxHold):")
    print()
    header = f"  {'Stag/Hold':>9}  " + "  ".join(f"{h:>5}m" for h in MAX_HOLD_VALUES)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for stag in STAGNATION_VALUES:
        row = f"  {stag:>8}m  "
        for hold in MAX_HOLD_VALUES:
            r = results.get((stag, hold))
            if r:
                ev = r['ev']
                # Markierung fuer beste Kombination
                marker = "*" if (stag == best['stag'] and hold == best['hold']) else " "
                row += f" {ev:>+5.0f}%{marker} "
            else:
                row += f"   n/a   "
        print(row)
    print()


def run(args: list = None):
    args = args or []

    if not DB_PATH.exists():
        print(f"\n[Fehler] observer_performance.db nicht gefunden.")
        print("  Tipp: Zuerst Observer-Mode ausfuehren.\n")
        return

    # Optionen parsen
    top_n = 10
    session_limit = None

    i = 0
    while i < len(args):
        if args[i] == "--top" and i + 1 < len(args):
            try: top_n = int(args[i+1])
            except ValueError: pass
            i += 2
        elif args[i] == "--sessions" and i + 1 < len(args):
            try: session_limit = int(args[i+1])
            except ValueError: pass
            i += 2
        else:
            i += 1

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Sessions laden
    all_sessions = [r[0] for r in conn.execute(
        "SELECT session_id FROM wallet_trades GROUP BY session_id ORDER BY MIN(timestamp) DESC"
    ).fetchall()]

    if session_limit:
        selected_sessions = all_sessions[:session_limit]
        print(f"\n  Simuliere letzte {session_limit} Sessions: {', '.join(s[:20] for s in selected_sessions)}")
    else:
        selected_sessions = None
        print(f"\n  Simuliere alle {len(all_sessions)} Sessions...")

    # Positionen laden
    positions = load_positions(conn, session_filter=selected_sessions)
    conn.close()

    if not positions:
        print("  Keine Positionen fuer Simulation gefunden.")
        return

    print(f"  {len(positions)} Positionen geladen.")
    print(f"  Teste {len(STAGNATION_VALUES) * len(MAX_HOLD_VALUES)} Kombinationen...")
    print()

    # Simulation
    results = run_simulation(positions)

    # Ausgabe
    print_results(results, top_n=top_n)
