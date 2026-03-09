# 📸 SNAPSHOT – Stand 04.03.2026 (Session 3)

**Projektpfad:** `C:\Users\phili\Documents\GitHub\copybot\bot`

---

## ⚠️ Bekannte Zustände & Hinweise

- `wallet_performance.db` – 12 Wallets, 492 Trades
- Confidence-Startwert für unbekannte Wallets: **0.2** (< 5 Trades)
- **High/Low Tracking läuft ab dieser Session korrekt** (Bug gefixt)
- Bisherige Trades haben `max_price_pct`/`min_price_pct = NULL` → dyn_SL/TP basieren noch auf Verlust-Exits
- Ab nächster Analyse-Session füllen sich die echten Werte → dyn_SL/TP werden präziser
- DB-Schema wurde migriert (Spalten vorhanden, Migration läuft auch automatisch beim Bot-Start)

---

## 🐛 In dieser Session gefixter Bug

**wallet_analysis.py**: `if not price_missing` war in _price_update_loop nicht definiert →
High/Low Tracking lief **nie**. Gefixt zu `if pos.entry_price_eur > 0`.

---

## 🆕 Änderungen in dieser Session

### wallet_tracker.py – Label-Logik verbessert
- RUNNER-Check jetzt mit `median_high` und `median_drawdown`:
  - Echter RUNNER: `median_high > avg_win * 0.8` UND `abs(median_drawdown) > 30`
  - Hohe Verlust-Exits aber flache Drawdowns → MIXED (kein falscher RUNNER)
- SCALPER-Check mit `median_drawdown`:
  - Gelegentliche Drawdowns > 35% → MIXED statt SCALPER
- RUNNER-Schwelle von `avg_win > 80` auf `avg_win > 60` gesenkt (realistischer)

### show_db.py – Dynamische SL/TP anzeigen
- Übersicht: Zeigt `dynamic_sl/tp` aus DB statt immer Label-Defaults
- `*` markiert dynamisch berechnete Werte (z.B. `-39%*` / `+40%*`)
- Detail-Ansicht: Zeigt `[dynamisch*]` oder `[label-default]` als Quelle

### migrate_and_recalc.py – Neues Hilfsskript
- Einmalig ausführen um Stats neu zu berechnen
- `cd bot && python migrate_and_recalc.py`

---

## 📁 Projektstruktur (relevante Dateien)

```
bot/
├── main.py
├── migrate_and_recalc.py          ← NEU: Einmalige DB-Migration + Neuberechnung
├── data/
│   └── wallet_performance.db      ← SQLite, 12 Wallets, 492 Trades
├── trading/
│   ├── wallet_tracker.py          ← Confidence, Labels, SL/TP, Inaktivitäts-Tags
│   ├── engine.py                  ← PaperTradingEngine
│   ├── price_oracle.py            ← DexScreener → Birdeye → CoinGecko
│   ├── connection_monitor.py
│   └── portfolio.py
├── runners/
│   ├── wallet_analysis.py         ← Haupt-Analyse-Modus (Bug gefixt: High/Low Tracking)
│   ├── paper_mainnet.py
│   ├── show_db.py                 ← Zeigt jetzt dyn_SL/TP aus DB
│   └── help.py
└── pattern/
    └── redundancy.py
```

---

## 🔑 Implementierte Features

### wallet_tracker.py
| Feature | Details |
|---|---|
| Confidence Score | WR 45% + Avg P&L 35% (logarithmisch-relativ) + Trade Count 20% |
| Startwert | 0.2 (unter 5 Trades) |
| Strategy Labels | ASYMMETRIC / RUNNER / SCALPER / LOSS_MAKER / MIXED / UNKNOWN |
| Label-Schwelle | 20 saubere Trades |
| **Label nutzt jetzt** | **median_drawdown (min_price_pct) + median_high (max_price_pct)** |
| SL/TP Priorität | 1. Dynamisch (Perzentile) → 2. Label-Defaults → 3. Global |
| Dynamische SL/TP | TP = 25. Perzentil Gewinne, SL = 75. Perzentil Lows + 10% Puffer |
| Dynamisch-Schwelle | 20 saubere Trades (mit High/Low Daten für SL, sonst Exit-Fallback) |
| **High/Low Tracking** | **jetzt korrekt aktiv** (Bug mit `price_missing` scope gefixt) |
| Inaktivitäts-Tags | max 3 Tags/Wallet; 3 Tags → Timeout 5 Min statt 10 Min |

**STRATEGY_SL_TP_DEFAULTS (Fallback wenn < 20 Trades):**
```
ASYMMETRIC  SL -35%  TP +150%
RUNNER      SL -50%  TP +175%
SCALPER     SL -20%  TP +40%
LOSS_MAKER  SL -25%  TP +50%
MIXED       SL -50%  TP +100%
UNKNOWN     SL -50%  TP +100%
```

### Label-Logik (neu)
```
LOSS_MAKER  : win_rate < 15%
ASYMMETRIC  : avg_win > 80% AND avg_loss < 45% AND profit_factor >= 1.0
RUNNER      : avg_win > 60% AND avg_loss >= 35%
               + wenn High/Low vorhanden:
                 - median_high > avg_win*0.8 AND abs(median_drawdown) > 30% → RUNNER
                 - abs(median_drawdown) <= 30% → MIXED (kein echter Runner)
SCALPER     : avg_win <= 50% AND avg_loss <= 25% AND win_rate >= 50%
               + wenn High/Low vorhanden:
                 - abs(median_drawdown) > 35% → MIXED
MIXED       : alles andere
```

### Aktueller DB-Zustand (nach Neuberechnung)
| Wallet (Prefix) | Trades | WR | Conf | Label | dyn_SL | dyn_TP |
|---|---|---|---|---|---|---|
| CAPn1yH4 | 11 | 55% | 0.304 | UNKNOWN | -- | -- |
| 5B79fMkc | 44 | 27% | 0.299 | RUNNER | -39% | +40% |
| CyaE1VxvB | 69 | 22% | 0.298 | **RUNNER** (war MIXED) | -32% | +20% |
| 71PCu3E4 | 12 | 42% | 0.235 | UNKNOWN | -- | -- |
| 86AEJExy | 24 | 25% | 0.213 | RUNNER | -30% | +101% |
| PMJA8UQD | 37 | 3% | 0.160 | LOSS_MAKER | -48% | +141% |
| CvNiezB8 | 10 | 10% | 0.085 | UNKNOWN | -- | -- |

---

## 🧠 Grundprinzipien (immer beachten)

1. **Realitätsnähe hat Priorität**
2. **Kein Preis = Totalverlust (0 EUR) + price_missing=True**
3. **Ausnahme Emergency Exit** – letzten bekannten Preis verwenden
4. **High/Low Tracking** – nur während Position offen, nur für Label (nicht SL/TP direkt)
5. **SL/TP** – aus Wallet-Exits ableiten (Perzentile), nicht aus Token-Verhalten nach dem Exit

---

## 🔮 Geplant (noch nicht implementiert)

### Auto-Optimizer
- Variiert Parameter: Confidence-Gewichtungen, Redundanz-Gewichtungen, min_wallets, min_confidence, time_window, SL%, TP%, MAX_PRICE_FAILURES
- Bewertet nach: Gesamt-P&L, Win Rate, Drawdown, Sharpe-ähnlicher Kennzahl
- Grid Search / Random Search / Bayesianische Optimierung
- Startet automatisierte Analyse-Durchläufe

---

## ▶️ Start-Befehle

```bash
cd C:\Users\phili\Documents\GitHub\copybot\bot

# DB migrieren + Stats neu berechnen (einmalig nach Update)
python migrate_and_recalc.py

# Wallet-Analyse starten
python main.py wallet_analysis

# DB anzeigen
python main.py show_db
python main.py show_db pnl
python main.py show_db wallet <PREFIX>
python main.py show_db sessions

# Paper Trading
python main.py paper_mainnet
```
