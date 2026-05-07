# SNAPSHOT Copybot 6 – Chat vom 2026-04-27

## Meta
- **Chat-Nummer:** 6
- **Datum:** 2026-04-27 bis 2026-05-07
- **Dateizugriff:** Claude in Chrome Filesystem MCP
- **Projektpfad:** `C:\Users\phili\Documents\GitHub\copybot`

---

## Was in diesem Chat erledigt wurde

### Setup & Infrastruktur
- Claude Filesystem-Zugriff eingerichtet (`snapshot/CLAUDE_SETUP.md`)
- `snapshot/CLAUDE_SETUP_FX.md` für copybotfx Chat erstellt
- GitHub → Server eingerichtet: `git clone`, `git pull` funktioniert ✅
- Snapshot-Struktur auf `snapshot/` Ordner umgestellt
- Live Log screen mit Scrollback: `screen -S livelog -h 5000`

### Neue Features
- **Parallel-Key Source** (`solana_parallel_source.py`) – Bug gefixt (Initial Load)
- **Candidate-Pool** auf 100 erweitert, Smart Selection nach Observer-Trades
- **wallet_list.py** – HTML Übersicht mit Webserver (Port 7432)
  - Ausschluss einzelner Trades mit Häkchen (gespeichert in `excluded_trades.json`)
  - Confidence Score Breakdown Popup (anklickbar)
  - Live-Neuberechnung ohne ausgeschlossene Trades

### Neue Confidence-Formel
```
score = (WinRate × 0.55 + tanh(AvgPnL/50) × 0.45) × min(n/100, 1.0)
```
- Trade-Faktor dämpft proportional bis 100 Trades
- Minimum 5 Trades für echten Score, sonst 0.0
- `recalc_confidence.py` für einmalige Neuberechnung aller Wallets

### Transaction Cost Model (`trading/cost_model.py`) ✅ NEU
```
Kosten pro Seite = Netzwerk-Fee + Swap-Fee (0.25%) + Price Impact + Market Drift + Failure Cost
Default Pool-Liquidität: ~$30K EUR
Typische Kosten: 1.3% - 4.5% pro Seite
```
- `effective_pnl_eur` = raw PnL − (BUY-Kosten + SELL-Kosten)
- Wird nur im Analysis-Modus angewendet, nicht im Observer-Modus

### Analysis-Modus überarbeitet ✅
- Transaktionskosten bei BUY und SELL eingerechnet
- Entry/Exit-Preis mit Kosten-Offset angezeigt
- PriceMonitor zeigt: `Raw PnL | Eff. PnL | Change%`
- SL/TP aus Observer-DB abgeleitet (via `_get_observer_sl_tp`)
- Ergebnis-Tabelle zeigt Raw PnL + Effective PnL + SL/TP pro Wallet

### wallet_tracker.py
- Neue DB-Felder: `cost_eur`, `effective_pnl_eur` in `wallet_trades`
- Neue Stats-Felder: `total_cost_eur`, `effective_pnl_eur` in `wallet_stats`
- `record_buy` + `record_sell` akzeptieren `cost_eur` / `entry_cost_eur`

---

## Aktueller Projektstand

### Infrastruktur
- **Server:** Kali Linux (`Shrimps-Kali`), `copybot@192.168.178.55` / Tailscale `100.93.6.111`
- **Bot:** läuft 24/7 in `screen -S copybot`
- **Live Log:** `screen -S livelog -h 5000`

### Screen-Befehle
```bash
screen -S copybot                    # Bot
screen -S livelog -h 5000            # Live Log mit Scrollback
screen -ls                           # Alle Sessions
screen -r copybot                    # Reconnect
screen -d <id> && screen -r <id>     # Force reconnect
# Ctrl+A, D → detach | Ctrl+A, [ → Scroll | q → Ende
```

### Git-Workflow
```bash
PC/Laptop:  git push
Server:     git -C ~/copybot pull
DBs:        python deploy.py sync
```

### Trade-Source Modi
```
[1] Multi-Key     → Top 20 Candidates
[2] Polling       → Top 20 Candidates
[3] Parallel N    → Top 20×N Candidates
```

### Wichtige Commands
```bash
python main.py wallet_analysis       # Bot starten
python main.py list                  # Wallet Übersicht (Browser)
python main.py list --analysis       # Analysis-DB Übersicht
python main.py logs                  # Session-Übersicht
python main.py keys                  # Helius Keys verwalten
python main.py live_log              # Live Log
python recalc_confidence.py          # Confidence Scores neu berechnen
python find_wallets.py --apply       # Candidate-Pool auffüllen
python deploy.py sync                # DBs synchronisieren
```

### Helius Keys
- 7 Keys, Key 1 leer, Keys 2–7 aktiv (6 aktive)
- Parallel mit 2 Keys → Top 40 Candidates

### Performance (letzte bekannte Sessions)
- `observer_20260502_163339`: ~20h, 209 Trades, PnL +3.028 EUR (paper)
- `observer_20260506_084046`: ~10h, 46 Trades, +184.485 EUR (Ausreißer: DNFdBy3b +185K)
- Beste echte Session: **+167.579 EUR** (März 2026)

### Offene Punkte
- `recalc_confidence.py` auf Server ausführen (nach git pull)
- Analysis-Session starten und mit Cost Model testen
- wallet_list.py: `effective_pnl_eur` aus Analysis-DB anzeigen
- Stagnation-Timeout von 15 auf 30 Min erhöhen (noch offen)
- Laptop-Workflow via Tailscale testen
- Dashboard: Freund baut auf API-Basis (Port 8080)
- copybotfx Pfad in Claude in Chrome Extension eintragen

---

## Wichtige Dateipfade
```
copybot/
├── snapshot/
│   ├── CLAUDE_SETUP.md              # Claude Filesystem-Zugriff (copybot + daphna)
│   ├── CLAUDE_SETUP_FX.md           # Setup für copybotfx Chat
│   └── SNAPSHOT_Copybot_6.md        # Dieser Snapshot
└── bot/
    ├── main.py
    ├── find_wallets.py              # MAX_CANDIDATES = 100
    ├── recalc_confidence.py         # Einmalige Score-Neuberechnung
    ├── config/network.py            # 7 Helius Keys
    ├── wallets/sync.py              # Smart Candidate Selection
    ├── trading/
    │   ├── wallet_tracker.py        # + cost_eur, effective_pnl_eur
    │   ├── cost_model.py            # Transaction Cost Model (NEU)
    │   └── price_oracle.py
    ├── runners/
    │   ├── wallet_analysis.py       # Analysis mit Kosten + Observer-SL/TP
    │   ├── wallet_list.py           # HTML Übersicht + Ausschluss + Breakdown
    │   ├── live_log.py
    │   ├── logs.py
    │   └── keys.py
    ├── observation/sources/
    │   ├── solana_ws_source.py      # Modus 1
    │   ├── solana_polling.py        # Modus 2
    │   └── solana_parallel_source.py # Modus 3 (Bug gefixt)
    └── data/
        ├── observer_performance.db
        ├── wallet_performance.db
        └── excluded_trades.json     # Ausgeschlossene Trades
```

## Repo
- GitHub: `https://github.com/0xphx/copybot.git` (privat)
- Server: `~/copybot` via git clone
