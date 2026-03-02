# 📊 Paper Trading System

## Übersicht

Das Paper Trading System ermöglicht es dir, den Bot mit **virtuellem Kapital** zu testen, ohne echtes Geld zu riskieren. Eine Einheit entspricht **1 EUR**.

## Features

✅ **Virtuelles Portfolio** - Startet mit 1000 EUR Kapital  
✅ **Automatisches Trading** - Bot handelt basierend auf Signals  
✅ **20% Position Size** - Jeder Trade nutzt 20% des Kapitals  
✅ **Exit Strategy** - Verkauft wenn Lead-Wallet verkauft  
✅ **EUR Preise** - Integriert mit Jupiter & CoinGecko  
✅ **Performance Tracking** - Win Rate, P&L, Statistiken  
✅ **Hybrid Testing** - Echte Mainnet Daten + Fake Trades  

## Wie es funktioniert

### 1. **Signal Detection**
- Redundancy Engine erkennt wenn 2+ Wallets das gleiche Token kaufen
- Confidence Score basierend auf Anzahl Wallets, Time Window, etc.

### 2. **Buy Execution**
- Bot holt EUR-Preis für Token
- Investiert 20% des verfügbaren Kapitals
- Erstellt Position mit Entry Price

### 3. **Sell Execution**
- Bot überwacht alle Lead-Wallets (die den Trade ausgelöst haben)
- Sobald ein Lead-Wallet verkauft → Bot verkauft auch
- Berechnet P&L in EUR und Prozent

### 4. **Portfolio Tracking**
- Alle Trades werden gespeichert
- Statistiken: Win Rate, Avg Win/Loss, Total P&L
- JSON Export am Ende der Session

## Installation

Keine zusätzlichen Dependencies nötig! Nutzt bereits vorhandene Packages.

## Usage

### Zwei Modi verfügbar:

#### 1. Hybrid Mode (Empfohlen für Testing)
```powershell
python main.py paper
```
- Mainnet + Fake Trades
- Schnellere Tests
- Garantierte Signals alle 20s
- Perfekt zum Testen der Bot-Logik

#### 2. Pure Mainnet Mode (Realistisch)
```powershell
python main.py paper_mainnet
```
- Nur echte Mainnet Trades
- Keine Fake Trades
- Realistischer aber langsamer
- Braucht aktive Wallets

### Was passiert:
1. Lädt deine Wallets aus der DB
2. Startet mit 1000 EUR virtuellem Kapital
3. Überwacht Mainnet + generiert Fake Trades (alle 20s)
4. Bot kauft automatisch bei Signals
5. Bot verkauft automatisch wenn Lead-Wallet verkauft

### Stoppen:
```
CTRL+C
```

Bot gibt dann automatisch:
- Portfolio Summary
- Win/Loss Statistiken
- Speichert JSON Report

## Beispiel Output

```
📊 PAPER TRADING MODE - Virtual Trading Test
============================================================

[Wallets] Loaded 5 wallets

🧠 [Trading Engine] Activated
   Initial Capital: 1000.00 EUR
   Position Size: 20%
   Strategy: Follow lead wallets

🧠 [Redundancy Engine] Activated
   Time Window: 30 seconds
   Min Wallets: 2
   Min Confidence: 50%

💉 [Hybrid] Injecting FAKE BUY pattern:
   Token: FakeToke...
   Wallets: 3

🔵 [hybrid_fake    ] ACTbvbNm... BUY   850.12 FakeToke...
🔵 [hybrid_fake    ] 9z3LRC24... BUY   890.88 FakeToke...
🔵 [hybrid_fake    ] CyaE1Vxv... BUY   833.71 FakeToke...

======================================================================
🚨 STRONG BUY SIGNAL DETECTED!
======================================================================
Token:        FakeToken111...
Side:         BUY
Wallets:      3 unique wallets
Confidence:   80%

[PaperPortfolio] 🟢 BOUGHT 2000.0000 FakeToke... @ 0.1000 EUR = 200.00 EUR
[PaperPortfolio] Cash remaining: 800.00 EUR

💉 [Hybrid] Injecting FAKE SELL pattern:
   Token: FakeToke...
   Wallets: 1

🔵 [hybrid_fake    ] ACTbvbNm... SELL  850.12 FakeToke...

[PaperPortfolio] 🟢 SOLD 2000.0000 FakeToke... @ 0.1050 EUR = 210.00 EUR
[PaperPortfolio] P&L: +10.00 EUR (+5.00%)
[PaperPortfolio] Cash: 1010.00 EUR

======================================================================
📊 PAPER TRADING PORTFOLIO SUMMARY
======================================================================
Initial Capital:           1000.00 EUR
Current Cash:              1010.00 EUR
Open Positions:                   0
Total Value:               1010.00 EUR
Total P&L:                  +10.00 EUR (+1.00%)
----------------------------------------------------------------------
Trades Completed:                 1
Winning Trades:                   1
Losing Trades:                    0
Win Rate:                    100.0%
Avg Win:                     +10.00 EUR
Avg Loss:                     +0.00 EUR
======================================================================
```

## Konfiguration

### Position Size ändern
In `trading/portfolio.py` Zeile 54:
```python
self.position_size_percent = 0.20  # 20% des Kapitals
```

### Startkapital ändern
In `runners/paper_trading.py` Zeile 47:
```python
initial_capital = 1000.0  # 1000 EUR
```

### Fake Trade Frequenz
In `runners/paper_trading.py` Zeile 81:
```python
fake_trade_interval=20  # Alle 20 Sekunden
```

### Redundancy Settings
In `runners/paper_trading.py` Zeile 58-62:
```python
RedundancyEngine(
    time_window_seconds=30,  # Zeitfenster
    min_wallets=2,           # Mind. Wallets
    min_confidence=0.5       # Schwelle
)
```

## Dateien

```
bot/
├── trading/
│   ├── portfolio.py         # Portfolio Management
│   ├── price_oracle.py      # EUR Preis Fetching
│   └── engine.py            # Trading Logic
├── runners/
│   └── paper_trading.py     # Paper Trading Runner
└── data/
    └── paper_trading_*.json # Gespeicherte Sessions
```

## Price Oracle

Der Bot nutzt:
1. **Jupiter API** - Primary für Solana Token Preise
2. **CoinGecko** - Fallback für bekannte Tokens (SOL, USDC, etc.)
3. **Mock Prices** - Für Testing wenn APIs nicht erreichbar

USD → EUR Conversion: 0.92 (wird später dynamisch)

## Nächste Schritte

Nach erfolgreichen Paper Trading Tests:

1. ✅ **Mainnet Testing** - Bot läuft bereits auf echtem Mainnet
2. ⏳ **Live Trading** - Integration mit echtem Wallet
3. ⏳ **Jupiter Swap** - Echte Swaps statt Paper Trading
4. ⏳ **Risk Management** - Stop Loss, Position Limits

## Tips

- **Genug Wallets**: Mehr Wallets = bessere Signals
- **Geduld**: Lass den Bot mehrere Stunden laufen
- **Analyse**: Schau dir die JSON Reports an
- **Tweaking**: Passe Redundancy Settings an basierend auf Resultaten

## Troubleshooting

### Keine Signals
- Prüfe ob Wallets aktiv sind
- Senke `min_confidence` auf 0.3
- Senke `min_wallets` auf 2

### Zu viele False Positives
- Erhöhe `min_confidence` auf 0.7
- Erhöhe `min_wallets` auf 3
- Reduziere `time_window_seconds`

### Keine EUR Preise
- Bot nutzt automatisch Mock Preise für Testing
- Für Production: CoinGecko API Key hinterlegen

## Support

Fragen? Schau in die Projekt-Dokumentation oder PROJECT_SNAPSHOT.md
