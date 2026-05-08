# SNAPSHOT Copybot 7 – Startpunkt für neuen Chat

## Meta
- **Chat-Nummer:** 7
- **Datum:** 2026-05-08
- **Projektpfad:** `C:\Users\phili\Documents\GitHub\copybot`
- **Dateizugriff:** Claude in Chrome Filesystem MCP
- **Setup-Datei:** `snapshot/CLAUDE_SETUP.md`

---

## Setup für Claude (am Chat-Anfang)

1. `tool_search` → `"filesystem read write"` → Filesystem-Tools laden
2. `filesystem:list_directory` → `C:\Users\phili\Documents\GitHub\copybot`
3. Diesen Snapshot lesen: `snapshot/SNAPSHOT_Copybot_7.md`
4. Erlaubte Pfade: `copybot` (lesen+schreiben), `daphna` (lesen+schreiben), `copybotfx` (nur lesen, schreiben auf Anfrage)

---

## Aktueller Projektstand

### Infrastruktur
- **Server:** Kali Linux (`Shrimps-Kali`), `copybot@192.168.178.55` / Tailscale `100.93.6.111`
- **Bot:** 24/7 in `screen -S copybot`
- **Live Log:** `screen -S livelog -h 5000`
- **Repo:** `https://github.com/0xphx/copybot.git` (privat, Freund ist Owner)

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

### Wichtige Commands
```bash
python main.py wallet_analysis       # Bot starten (Observer oder Analysis)
python main.py list                  # Wallet Übersicht im Browser (Port 7432)
python main.py list --analysis       # Analysis-DB Übersicht
python main.py logs                  # Session-Übersicht
python main.py keys                  # Helius Keys verwalten
python main.py live_log              # Live Log
python recalc_confidence.py          # Confidence Scores neu berechnen (einmalig)
python find_wallets.py --apply       # Candidate-Pool auffüllen
python deploy.py sync                # DBs synchronisieren
```

---

## Bot-Modi & Konfiguration

### Trade-Source Modi (beim Start wählbar)
```
[1] Multi-Key     → sequenzielle Helius Key-Rotation → Top 20 Candidates
[2] Polling       → einzelner Helius Key             → Top 20 Candidates
[3] Parallel-Key  → N Keys gleichzeitig              → Top 20×N Candidates
```

### Analysis-Modus (NEU, vollständig überarbeitet)
```
- Eigener SL/TP aus Observer-DB abgeleitet
- Transaktionskosten (cost_model.py) berechnet:
    Netzwerk-Fee + Swap-Fee (0.25%) + Price Impact (x*y=k) + Market Drift + Failure Rate
    Default Pool: ~$30K EUR → ~1.3% Kosten pro Seite
- BUY-Signal Redundanz-Filter:
    Min. X Wallets kaufen denselben Token innerhalb von Y Sekunden
    + Gesamt-Confidence aller kaufenden Wallets >= Z
    → verhindert Einzelausreisser
- PriceMonitor zeigt: Raw PnL | Eff. PnL (nach Kosten)
- Ergebnis-Tabelle: Raw PnL + Effective PnL nebeneinander
```

### Observer-Modus
```
- Folgt Wallet 1:1, kein SL/TP
- Stagnation-Timeout: 15 Min kein Preischange → schliessen
- Max-Haltedauer: 60 Min → schliessen (konfigurierbar)
- Anti-Softlock: Totalverlust nach 10x kein Preis / 30 Min ohne Preis
- Auto: evaluate_wallets + find_wallets --apply nach Session-Ende
```

---

## Candidate-System
```
Pool:        100 Candidates (MAX_CANDIDATES in find_wallets.py)
Beobachtet:  Top N nach Observer-Trades (meiste Trades = nächste zur Grenze)
Grenze:      20 clean SELLs → evaluate_wallets → Active oder Archived
Auffüllen:   automatisch nach Session-Ende + manuell: find_wallets.py --apply
Problem:     Filter ggf. zu streng → lockern falls keine neuen Wallets gefunden
```

## Confidence Score Formel
```
score = (WinRate × 0.55 + tanh(AvgPnL/50) × 0.45) × min(n/100, 1.0)
- Trade-Faktor: lineare Dämpfung bis 100 Trades
- Minimum 5 Trades für echten Score, sonst 0.0
- recalc_confidence.py für einmalige Neuberechnung aller bestehenden Wallets
```

---

## Bekannte Bugs / Fixes in Chat 6

### Parallel-Source Initial Load Bug (gefixt ✅)
- **Problem:** `initial_done = slot is not None` war immer True → alle historischen TXs wurden beim Start als neue Trades verarbeitet → Massen-BUYs beim Start
- **Fix:** `slot.initial_done` als Attribut auf `_KeySlot`, `process=slot.initial_done` an `_process_signatures` übergeben

### Observer PriceMonitor stoppt nach letztem SELL (bekannt)
- Nach dem letzten SELL wird PriceMonitor gestoppt
- Wenn danach keine neuen BUYs kommen, läuft Bot im Leerlauf
- Ursache: Wallets waren inaktiv, kein Fehler im Bot

---

## Offene Punkte
- `recalc_confidence.py` auf Server ausführen (nach git pull, einmalig)
- Analysis-Modus erste Session starten und testen
- wallet_list.py: `effective_pnl_eur` aus Analysis-DB besser anzeigen
- Stagnation-Timeout von 15 auf 30 Min erhöhen (noch nicht gemacht)
- Laptop-Workflow via Tailscale testen
- Dashboard (Freund, API Port 8080)
- copybotfx Pfad in Claude in Chrome Extension eintragen
- Ausreißer-Trades analysieren (DNFdBy3b +185K EUR – Oracle-Bug oder echter Trade?)

---

## Helius Keys
- 7 Keys in `config/network.py`, Key 1 leer, Keys 2–7 aktiv (6 aktive)
- Parallel mit 2 Keys → Top 40 Candidates gleichzeitig

## Performance (letzte bekannte Sessions)
- `observer_20260502_163339`: ~20h, 209 Trades, +3.028 EUR (paper, bereinigt)
- `observer_20260506_084046`: ~10h, 46 Trades, +184.485 EUR (Ausreißer: DNFdBy3b)
- Beste echte Session: **+167.579 EUR** (März 2026)

---

## Wichtige Dateipfade
```
copybot/
├── snapshot/
│   ├── CLAUDE_SETUP.md              # Claude Filesystem-Zugriff (copybot + daphna)
│   ├── CLAUDE_SETUP_FX.md           # Setup für copybotfx Chat
│   ├── SNAPSHOT_Copybot_6.md        # Vorheriger Snapshot
│   └── SNAPSHOT_Copybot_7.md        # Dieser Snapshot
└── bot/
    ├── main.py
    ├── find_wallets.py              # MAX_CANDIDATES = 100
    ├── recalc_confidence.py         # Einmalige Score-Neuberechnung
    ├── config/network.py            # 7 Helius Keys
    ├── wallets/sync.py              # Smart Candidate Selection
    ├── trading/
    │   ├── wallet_tracker.py        # + cost_eur, effective_pnl_eur Felder
    │   ├── cost_model.py            # Transaction Cost Model
    │   └── price_oracle.py
    ├── runners/
    │   ├── wallet_analysis.py       # Analysis (Kosten + Redundanz-Filter) + Observer
    │   ├── wallet_list.py           # HTML Übersicht (Port 7432) + Trade-Ausschluss
    │   ├── live_log.py
    │   ├── logs.py
    │   └── keys.py
    ├── observation/sources/
    │   ├── solana_ws_source.py      # Modus 1
    │   ├── solana_polling.py        # Modus 2
    │   └── solana_parallel_source.py # Modus 3 (Initial Load Bug gefixt)
    └── data/
        ├── observer_performance.db
        ├── wallet_performance.db
        └── excluded_trades.json     # Ausgeschlossene Trades (wallet_list)
```
