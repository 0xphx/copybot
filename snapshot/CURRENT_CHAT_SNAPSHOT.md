# COPYBOT – CHAT SNAPSHOT
_Erstellt: 2026-03-02 | Für neuen Chat nach aufgehängter Session_

---

## 🔧 ARBEITSWEISE FÜR DEN NEUEN CHAT

Hallo Claude!

Ich arbeite an einem Solana Copy Trading Bot im Verzeichnis `C:\Users\phili\Documents\GitHub\copybot\bot`.

### Wichtige Regeln – IMMER befolgen:
- ✅ Führe Änderungen **DIREKT** aus – nutze `Filesystem:write_file` für Windows Paths
- ✅ **Überschreibe** Dateien wenn nötig
- ✅ Lese Dateien vor dem Ändern
- ❌ **NIEMALS** Dateien zum Download anbieten
- ❌ **NIEMALS** fragen ob du überschreiben darfst – tu es einfach
- ❌ **NIEMALS** sagen „füge XY selbst ein"

### Bestätigung
Antworte mit:
> ✅ Verstanden! Vollständige Schreibrechte auf `C:\Users\phili\Documents\GitHub\copybot\bot`. Bereit!

---

## 📁 PROJEKT-STRUKTUR

```
C:\Users\phili\Documents\GitHub\copybot\bot\
├── main.py                              # Entry point – alle Commands
├── runners/
│   ├── paper_mainnet.py                 # Paper Trading Runner (Mainnet)
│   ├── wallet_analysis.py               # Wallet Analyse Runner ← ZULETZT GEÄNDERT
│   ├── show_db.py                       # DB Viewer im Terminal
│   ├── help.py                          # Help-Output
│   └── ...
├── trading/
│   ├── engine.py                        # PaperTradingEngine (SL/TP, Price Monitor)
│   ├── portfolio.py                     # PaperPortfolio (Positionen, P&L)
│   ├── price_oracle.py                  # Preis-Fetching (Jupiter → DexScreener → Birdeye → CoinGecko)
│   ├── wallet_tracker.py                # SQLite DB für Wallet-Performance & Confidence Scores
│   └── connection_monitor.py            # Health Monitoring
├── observation/
│   └── sources/solana_polling.py        # Solana Transaction Polling
├── pattern/
│   └── redundancy.py                    # RedundancyEngine – Signal-Erkennung + Confidence
├── wallets/
│   └── sync.py                          # Wallet-Liste laden
└── data/
    └── wallet_performance.db            # SQLite DB (wird automatisch erstellt)
```

---

## 🚀 VERFÜGBARE COMMANDS

```
python main.py paper_mainnet       # Paper Trading (Mainnet, interaktive Config)
python main.py wallet_analysis     # Jedes Wallet einzeln analysieren, DB befüllen
python main.py show_db             # DB anzeigen (sortiert nach Confidence)
python main.py show_db pnl         # Sortiert nach P&L
python main.py show_db winrate     # Sortiert nach Win-Rate
python main.py show_db trades      # Sortiert nach Trade-Anzahl
python main.py show_db --min 5     # Nur Wallets mit mind. 5 Trades
python main.py show_db sessions    # Alle Sessions
python main.py show_db wallet XYZ  # Detail eines Wallets (Prefix reicht)
python main.py help                # Diese Übersicht
```

---

## ✅ AKTUELLE FEATURES

### paper_mainnet
- Interaktive Konfiguration beim Start (9 Parameter: Kapital, Position Size, Time Window, Min Wallets, Min Confidence, Connection Timeout, Price Update Interval, Stop-Loss, Take-Profit)
- **Stop-Loss: -50%** (Standard) | **Take-Profit: +100%** (Standard)
- **Max. 1 offene Position** gleichzeitig (global)
- Price Monitor Loop alle X Sekunden mit P&L-Anzeige
- Visuelle BUY Signal Box + SELL Signal Box
- RedundancyEngine mit historischen Confidence Scores (falls DB vorhanden)
- Connection Health Monitoring + Emergency Exit bei Network Outage
- Hybrid Approach für Missed SELLs nach Reconnect
- Adaptive Polling (5s normal / 0.5s fast)
- SELL-Detection: wenn Trigger-Wallet genau diesen Token verkauft

### wallet_analysis
- Interaktive Konfiguration: **Max. gleichzeitige Positionen** (Standard: 1)
- **1000 EUR Startkapital pro Wallet**, **20% pro Trade** (= 200 EUR)
- **Stop-Loss: -50%** | **Take-Profit: +100%** (fest, keine Config)
- Gleiche visuelle Darstellung wie paper_mainnet (BUY-Box, SELL-Box, Price Monitor)
- Jedes Wallet hat ein eigenes `WalletAccount`-Objekt
- Globaler Positions-Slot: bei `max_positions=1` blockiert eine offene Position alle weiteren BUYs
- Beim Shutdown: **alle** offenen Positionen werden korrekt geschlossen
- Alle Trades → `wallet_performance.db` → Confidence Score wird aktualisiert
- Abschluss-Tabelle: Wallet | Trades | Win% | P&L | Confidence

### wallet_tracker (SQLite)
- Datenbank: `data/wallet_performance.db`
- Tabellen: `wallet_trades`, `wallet_stats`
- **Confidence Score Formel** (mind. 5 Trades):
  - 60% → Win Rate
  - 20% → Trade Count (sättigt bei 50)
  - 20% → Avg P&L (normiert auf ±50 EUR)
- Unter 5 Trades → neutral = 0.5

### redundancy.py
- Ohne DB: Wallet Count + Timing + Konsistenz
- Mit DB (`wallet_tracker`): 40% historischer Score + 30% Timing + 20% Wallet Count + 10% Konsistenz
- Fallback auf Basic-Logik wenn alle Wallets neutral (0.5)

### price_oracle.py
- Waterfall: Jupiter v6 → Jupiter Lite → DexScreener → Birdeye → CoinGecko → Mock (0.01 EUR)
- Session Management (prüft ob Session geschlossen ist)
- Timeout: 8s
- Statistiken: Total Fetches / Cache Hits / API Misses / Success Rate

---

## 📋 LETZTE ÄNDERUNGEN (diese Session)

| Datei | Was |
|-------|-----|
| `runners/wallet_analysis.py` | 1000 EUR/20% korrekt angezeigt; Shutdown schließt alle offenen Positionen aus `open_positions` (nicht nur `active_token`) |

### Letzter Stand vor Chat-Absturz:
Der Chat hing beim nächsten Feature-Request auf. **Nichts ist halb-fertig.** Alle Dateien sind konsistent.

---

## 🔮 NÄCHSTE MÖGLICHE SCHRITTE (offen)

_Keine offenen Aufgaben – der Chat ist an einem sauberen Zustand abgebrochen._

---

## ⚠️ BEKANNTE EIGENHEITEN

- `price_oracle.py` nutzt `USD × 0.92` als EUR-Näherung (kein Live-FX-Kurs)
- `show_db.py wallet`-Detail: Entry-Preis in der Trade-Tabelle zeigt aktuell Exit-Preis (kleiner Bug – `t['price_eur']` statt `t.get('entry_price_eur', ...)`)
- `help.py` zeigt noch `200 EUR` für `wallet_analysis` (veraltet, ist eigentlich 1000 EUR)
