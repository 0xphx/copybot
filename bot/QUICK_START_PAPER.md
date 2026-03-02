# 🚀 QUICK START - Paper Trading

## Schritt 1: Module testen
```powershell
cd C:\Users\phili\Documents\GitHub\copybot\bot
python test_paper_trading.py
```

**Erwartetes Output:**
```
Testing Paper Trading System...

[1/5] Testing trading module...
✅ Trading module OK
[2/5] Testing observation module...
✅ Observation module OK
[3/5] Testing pattern module...
✅ Pattern module OK
[4/5] Testing config module...
✅ Config module OK
[5/5] Testing wallets module...
✅ Wallets module OK

============================================================
✅ ALL MODULES OK - Ready for Paper Trading!
============================================================

Start with: python main.py paper
```

---

## Schritt 2: Wallets hinzufügen (heute Abend)

### Option A: JSON Import
1. Bearbeite `data/axiom_wallets.json`
2. Füge neue Wallets hinzu:
```json
[
  {"wallet": "NEUE_WALLET_ADRESSE_1", "category": "SmartWallet"},
  {"wallet": "NEUE_WALLET_ADRESSE_2", "category": "SmartWallet"}
]
```
3. Importiere:
```powershell
python main.py import
```

### Option B: Direkt in DB
Nutze einen SQLite Browser und füge direkt in `data/axiom.db` hinzu.

---

## Schritt 3: Paper Trading starten

### Zwei Modi verfügbar:

**Option A: Hybrid Mode (Empfohlen für erste Tests)**
```powershell
python main.py paper
```
- Mainnet + Fake Trades
- Garantierte Action alle 20s
- Schneller zum Testen

**Option B: Pure Mainnet (Realistischer)**
```powershell
python main.py paper_mainnet
```
- Nur echte Mainnet Trades
- Kann langsam sein wenn Wallets inaktiv
- Realistischere Ergebnisse

---

### Was du sehen wirst (Hybrid Mode):

1. **Startup:**
```
📊 PAPER TRADING MODE - Virtual Trading Test
============================================================

[Wallets] Loaded 5 wallets

🧠 [Trading Engine] Activated
   Initial Capital: 1000.00 EUR
   Position Size: 20%
```

2. **Trade Detection:**
```
🔵 [hybrid_fake] ACTbvbNm... BUY 850.12 FakeToke...
🔵 [hybrid_fake] 9z3LRC24... BUY 890.88 FakeToke...
```

3. **Signal Detection:**
```
🚨 STRONG BUY SIGNAL DETECTED!
Token:        FakeToken111...
Wallets:      3 unique wallets
Confidence:   80%
```

4. **Automatic Buy:**
```
[PaperPortfolio] 🟢 BOUGHT 2000.0000 FakeToke...
                 @ 0.1000 EUR = 200.00 EUR
[PaperPortfolio] Cash remaining: 800.00 EUR
```

5. **Automatic Sell:**
```
[PaperPortfolio] 🟢 SOLD 2000.0000 FakeToke...
                 @ 0.1050 EUR = 210.00 EUR
[PaperPortfolio] P&L: +10.00 EUR (+5.00%)
```

---

## Schritt 4: Laufen lassen

- Lass den Bot **mindestens 1-2 Stunden** laufen
- Er generiert alle 20s neue Fake Patterns
- Nach 30-60s verkaufen Lead-Wallets
- Bot handled automatisch

---

## Schritt 5: Stoppen & Analyse

### Stoppen:
```
CTRL+C
```

### Output:
```
📊 PAPER TRADING SESSION ENDED
============================================================

📈 Trading Statistics:
   Total Signals:    25
   Total Buys:       18
   Total Sells:      15

======================================================================
📊 PAPER TRADING PORTFOLIO SUMMARY
======================================================================
Initial Capital:           1000.00 EUR
Current Cash:               985.32 EUR
Open Positions:                   3
Total Value:               1045.67 EUR
Total P&L:                  +45.67 EUR (+4.57%)
----------------------------------------------------------------------
Trades Completed:                15
Winning Trades:                   9
Losing Trades:                    6
Win Rate:                     60.0%
Avg Win:                     +12.34 EUR
Avg Loss:                     -5.67 EUR
======================================================================

💾 Portfolio saved to: data/paper_trading_20260206_213045.json
```

---

## Interpretation der Ergebnisse

### ✅ Gute Zeichen:
- Win Rate > 50%
- Total P&L positiv
- Avg Win > Avg Loss
- Wenige offene Positionen am Ende

### ⚠️ Schlechte Zeichen:
- Win Rate < 40%
- Total P&L stark negativ
- Viele offene Positionen (Bot verkauft nicht)
- Avg Loss > Avg Win

---

## Häufige Probleme & Fixes

### Problem: Keine Signals
**Fix:**
```python
# In runners/paper_trading.py Zeile 58
RedundancyEngine(
    time_window_seconds=30,
    min_wallets=2,        # ← Von 2 auf 1 senken
    min_confidence=0.3    # ← Von 0.5 auf 0.3 senken
)
```

### Problem: Zu viele False Positives
**Fix:**
```python
# In runners/paper_trading.py Zeile 58
RedundancyEngine(
    time_window_seconds=20,  # ← Kürzer
    min_wallets=3,           # ← Höher
    min_confidence=0.7       # ← Höher
)
```

### Problem: Bot verkauft nicht
**Fix:**
- Stelle sicher dass `_generate_fake_sell_pattern()` läuft
- Check logs für "Injecting FAKE SELL pattern"
- Prüfe ob Trigger-Wallets korrekt getrackt werden

---

## Nächste Schritte nach erfolgreichen Tests

1. ✅ Analysiere JSON Reports
2. ✅ Optimiere Redundancy Settings
3. ✅ Teste mit mehr Wallets
4. ⏳ Integration mit echtem Jupiter Swap
5. ⏳ Risk Management hinzufügen

---

## Support Files

- **Vollständige Doku:** `PAPER_TRADING.md`
- **Projekt Status:** `PROJECT_SNAPSHOT.md`
- **Trade History:** `data/paper_trading_*.json`

---

**Viel Erfolg beim Testing! 🚀📊**
