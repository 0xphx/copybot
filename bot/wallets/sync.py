import sqlite3
from pathlib import Path
from wallets.repository import load_active_wallets
from wallets.models import ActiveWallet

# Wie viele Candidates pro Key beobachtet werden
CANDIDATES_PER_KEY = 20

# Pfad zur Observer-DB fuer Trade-Zaehlung
OBSERVER_DB = Path("data/observer_performance.db")


def _count_observer_trades(wallets: list[str]) -> dict[str, int]:
    """
    Zaehlt saubere SELLs pro Wallet aus der Observer-DB.
    Gibt {wallet: count} zurueck. Wallets ohne Eintraege bekommen 0.
    Robust: gibt leeres Dict zurueck wenn DB nicht existiert.
    """
    if not OBSERVER_DB.exists():
        return {w: 0 for w in wallets}

    try:
        conn = sqlite3.connect(str(OBSERVER_DB), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        placeholders = ",".join("?" for _ in wallets)
        rows = conn.execute(f"""
            SELECT wallet, COUNT(*) as cnt
            FROM wallet_trades
            WHERE wallet IN ({placeholders})
              AND side = 'SELL'
              AND reason NOT IN ('SESSION_ENDED', 'CRASH_RECOVERY')
              AND price_missing = 0
            GROUP BY wallet
        """, wallets).fetchall()
        conn.close()
        counts = {w: 0 for w in wallets}
        for wallet, cnt in rows:
            counts[wallet] = cnt
        return counts
    except Exception:
        return {w: 0 for w in wallets}


def sync_wallets(num_parallel_keys: int = 1) -> list[ActiveWallet]:
    """
    Zentrale Kontrollstelle fuer welche Wallets beobachtet werden.

    ActiveWallets + OwnWallets: immer alle dabei.

    CandidateWallets: aus dem Pool (bis zu 100) werden die
    Top (CANDIDATES_PER_KEY * num_parallel_keys) nach Observer-Trade-Anzahl
    ausgewaehlt. Das bringt die vielversprechendsten Candidates am schnellsten
    zur 20-Trade-Grenze.

    num_parallel_keys:
      - Multi-Key / Polling: 1  -> 20 Candidates
      - Parallel N Keys:     N  -> 20*N Candidates
    """

    # Alle aktiven Wallets laden (ohne Limit, wir filtern selbst)
    all_wallets = load_active_wallets(
        categories=["OwnWallet", "ActiveWallet", "CandidateWallet"],
        limit=None
    )

    # Nach Kategorie trennen
    own_and_active = [w for w in all_wallets if w.category in ("OwnWallet", "ActiveWallet")]
    candidates     = [w for w in all_wallets if w.category == "CandidateWallet"]

    # Candidates nach Observer-Trades sortieren (meiste Trades zuerst)
    candidate_limit = CANDIDATES_PER_KEY * max(1, num_parallel_keys)

    if candidates:
        candidate_addrs = [w.wallet for w in candidates]
        trade_counts    = _count_observer_trades(candidate_addrs)

        # Sortieren: meiste Trades zuerst, bei Gleichstand stabil
        candidates_sorted = sorted(
            candidates,
            key=lambda w: trade_counts.get(w.wallet, 0),
            reverse=True
        )
        selected_candidates = candidates_sorted[:candidate_limit]

        # Info ausgeben
        total_pool = len(candidates)
        watching   = len(selected_candidates)
        top_counts = [(w.wallet[:8], trade_counts.get(w.wallet, 0)) for w in selected_candidates[:5]]
        print(f"[WalletSync] Candidates: {watching}/{total_pool} beobachtet "
              f"(Top 20 pro Key, {num_parallel_keys} Key(s))")
        print(f"[WalletSync] Top Candidates: "
              + "  ".join(f"{addr}...={cnt}T" for addr, cnt in top_counts))
    else:
        selected_candidates = []

    # Zusammenfuehren: ActiveWallets + ausgewaehlte Candidates
    result = own_and_active + selected_candidates

    # Deduplizierung
    unique = {}
    for w in result:
        unique[w.wallet] = w
    active_wallets = list(unique.values())

    print(f"[WalletSync] Gesamt: {len(active_wallets)} Wallets "
          f"({len(own_and_active)} Active/Own + {len(selected_candidates)} Candidates)")

    return active_wallets
