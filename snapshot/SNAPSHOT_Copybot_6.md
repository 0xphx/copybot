# SNAPSHOT Copybot 6 – Chat vom 2026-04-27

## Meta
- **Chat-Nummer:** 6
- **Datum:** 2026-04-27
- **Dateizugriff:** Claude in Chrome Filesystem MCP (direkter Zugriff auf Originaldateien)
- **Projektpfad:** `C:\Users\phili\Documents\GitHub\copybot`

---

## Session-Zusammenfassung

### Was in diesem Chat erledigt wurde

#### 1. Projekt eingelesen
- ZIP-Upload + direkter Filesystem-Zugriff eingerichtet
- Alle Kerndateien gelesen

#### 2. Claude Filesystem-Zugriff eingerichtet
- `snapshot/CLAUDE_SETUP.md` erstellt
- Voraussetzung: Claude in Chrome Extension + Filesystem MCP aktiv

#### 3. GitHub → Server Einrichtung ✅
- Repo: `https://github.com/0xphx/copybot.git` (privat, gehört Freund)
- `git clone` mit Personal Access Token (HTTPS) erfolgreich
- Token versehentlich im Chat sichtbar → sofort widerrufen + neues Token gesetzt
- `git pull` getestet → "Bereits aktuell" ✅
- `deploy.py update` nutzt intern bereits `git pull` → kein Umbau nötig

#### 4. Snapshot-Struktur geändert
- Alle zukünftigen Snapshots kommen in den `snapshot/` Ordner
- Claude führt während des Chats eine laufende Snapshot-Datei (diese hier)

#### 5. Live Log – screen Scrollback ✅
- Problem: Terminal-Modus nicht scrollbar
- Lösung: `screen -S livelog -h 5000` → 5000 Zeilen Scrollback-Buffer
- Scroll-Modus: `Ctrl+A`, `[` → Pfeiltasten → `q` zum Beenden

#### 6. Parallel-Key Modus implementiert ✅
- Neue Datei: `bot/observation/sources/solana_parallel_source.py`
- `wallet_analysis.py` angepasst: Modus [3] beim Source-Start
- Beim Start wählbar: Anzahl parallele Keys (1 bis max verfügbare Keys)
- Wallets werden gleichmäßig auf Keys aufgeteilt (kein Overlap)
- Dynamisches Rebalancing wenn ein Key erschöpft ist
- Fallback auf Public RPCs wenn alle Keys erschöpft

---

## Aktueller Projektstand

### Infrastruktur
- **Server:** Kali Linux (`Shrimps-Kali`), User `copybot`
  - Lokal: `192.168.178.55`
  - Tailscale: `100.93.6.111`
- **Bot:** 24/7 in `screen -S copybot`, aktuell keine aktive Session
- **Live Log:** `screen -S livelog -h 5000` (Terminal-Modus, stündlich)

### Screen-Befehle
```bash
screen -S copybot                              # Bot-Screen
screen -S livelog -h 5000                      # Live Log mit Scrollback
screen -ls                                     # Alle Sessions
screen -r copybot / screen -r livelog          # Wiederverbinden
# Ctrl+A, D → detach | Ctrl+A, [ → Scroll-Modus | q → Scroll beenden
```

### Git-Workflow
```bash
PC/Laptop:  git push
Server:     git -C ~/copybot pull
DBs:        python deploy.py sync
```

### Trade-Source Modi (beim Start wählbar)
```
[1] Multi-Key     – sequenzielle Helius Key-Rotation (Standard)
[2] Polling       – einzelner Helius Key
[3] Parallel-Key  – N Keys gleichzeitig, Wallets aufgeteilt (NEU)
                    Beim Start: Anzahl Keys eingeben (1 bis max verfügbar)
```

### Helius Keys
- 7 Keys konfiguriert in `config/network.py`
- Key 1 leer, Keys 2–7 aktiv
- Parallel-Modus: bis zu 6 Keys gleichzeitig nutzbar

### Bot-Modi
- **Observer Mode** (`observer_` prefix): Folgt Wallets 1:1, kein SL/TP
- **Analysis Mode** (`analysis_` prefix): Eigener SL/TP (-50% / +100% default)

### Performance (letzte bekannte Sessions)
- `observer_20260425_210731`: 26h, 44 Trades, **-1842 EUR**
- `observer_20260426_233400`: positiv trending
- Beste Session: **+167.579 EUR** (März 2026)

### Offene Punkte
- Parallel-Modus testen (noch nicht live geführt)
- Laptop-Workflow via Tailscale testen (morgen Schule)
- Candidate-Slots ggf. erhöhen wenn Parallel-Modus läuft
- Live Log weiter verfeinern nach Bedarf
- Dashboard: Freund baut auf API-Basis (Port 8080)

---

## Wichtige Dateipfade
```
copybot/
├── deploy.py
├── .devices.json                        # Geräte mit IPs (lokal, nicht Git)
├── devices.template.json
├── WORKFLOW.md
├── snapshot/
│   ├── CLAUDE_SETUP.md                 # Claude Filesystem-Zugriff Anleitung
│   └── SNAPSHOT_Copybot_6.md           # Dieser Snapshot
└── bot/
    ├── main.py
    ├── config/network.py               # 7 Helius Keys
    ├── runners/
    │   ├── wallet_analysis.py          # Hauptrunner (3 Source-Modi)
    │   ├── live_log.py
    │   ├── logs.py
    │   └── keys.py
    ├── observation/sources/
    │   ├── solana_ws_source.py         # Multi-Key Rotation (Modus 1)
    │   ├── solana_polling.py           # Einzelner Key (Modus 2)
    │   └── solana_parallel_source.py   # Parallel-Key (Modus 3, NEU)
    ├── trading/
    │   ├── wallet_tracker.py
    │   └── price_oracle.py
    └── data/
        ├── observer_performance.db
        └── wallet_performance.db
```

---

## Repo
- GitHub: `https://github.com/0xphx/copybot.git` (privat)
- Server: `~/copybot` via git clone
