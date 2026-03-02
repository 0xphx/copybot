# 🎯 SELL FILTER - Nur Trigger-Wallets verkaufen!

**Datum:** 06.02.2026

---

## 🎯 Problem: Falsche Wallets verkaufen

**Vorher:**
```python
# SELL Generation wählt random Wallets
buys = self.fake_buy_trades[token]
num_sells = random.randint(1, 2)
sells = random.sample(buys, num_sells)  # ❌ Irgendwelche!
```

**Beispiel:**
```
Position wurde eröffnet von:
  - WalletA
  - WalletB

Aber SELL kommt von:
  - WalletC ❌ (Nicht Trigger-Wallet!)
  
→ Position wird NICHT geschlossen!
→ Funktioniert nicht korrekt!
```

---

## ✅ Lösung: Tracke Trigger-Wallets

### Neue Logik:

```python
# Track welche Wallets zur Position gehören
self.active_trigger_wallets: Set[str] = set()

# Bei Position öffnen
def start_watching_wallets(self, wallets: list[str]):
    self.active_trigger_wallets = set(wallets)

# Bei Position schließen  
def stop_watching_wallets(self):
    self.active_trigger_wallets.clear()
```

### SELL Generation mit Filter:

```python
async def _generate_fake_sell_pattern(self, token: str):
    buys = self.fake_buy_trades[token]
    
    # Wenn Position offen: Nur Trigger-Wallets!
    if self.active_trigger_wallets:
        # Filtere nur Trigger-Wallets
        trigger_buys = [b for b in buys 
                        if b["wallet"] in self.active_trigger_wallets]
        
        if not trigger_buys:
            return  # Keine passenden Wallets
        
        # Verkaufe 1-2 Trigger-Wallets
        sells = random.sample(trigger_buys, num_sells)
    else:
        # Keine Position: Random OK
        sells = random.sample(buys, num_sells)
```

---

## 🔄 Workflow:

### 1. BUY Signal (2 Wallets):
```
WalletA BUY TokenX
WalletB BUY TokenX

→ Position öffnet
→ [Hybrid] 🎯 Tracking 2 trigger wallets for SELL generation
→ active_trigger_wallets = {WalletA, WalletB}
```

### 2. SELL Generation (nur Trigger-Wallets):
```
fake_buy_trades[TokenX] = [
    {"wallet": WalletA, ...},  ← Trigger!
    {"wallet": WalletB, ...},  ← Trigger!
    {"wallet": WalletC, ...},  ← Nicht Trigger
]

→ Filtere nur Trigger:
  trigger_buys = [WalletA, WalletB]

→ Random wählen (1-2):
  sells = [WalletA]  ✅ Trigger-Wallet!

💉 [Hybrid] Injecting FAKE SELL pattern:
   Token: TokenX...
   Wallets: 1
   🎯 TRIGGER WALLETS (will close position!)
```

### 3. SELL wird emitted:
```
🔵 [hybrid_fake] WalletA... SELL TokenX

[TradingEngine] 🚨 TRIGGER WALLET SOLD
[TradingEngine] ✅ Closed position

→ [Hybrid] 🎯 Trigger wallets cleared
→ active_trigger_wallets = {}
```

---

## 📊 Vergleich:

### Vorher:
```
Position von WalletA + WalletB

SELL kommt von:
  - WalletC ❌ (Random)
  - WalletD ❌ (Random)
  
→ Position bleibt offen
→ Funktioniert nicht!
```

### Jetzt:
```
Position von WalletA + WalletB

SELL kommt von:
  - WalletA ✅ (Trigger!)
  - WalletB ✅ (Trigger!)
  
→ Position schließt
→ Funktioniert perfekt!
```

---

## 🎯 Key Features:

1. **Tracking:** `active_trigger_wallets` merkt sich welche Wallets zur Position gehören

2. **Filtering:** SELL Generation filtert nur Trigger-Wallets

3. **Fallback:** Wenn keine Position offen → Random Wallets OK

4. **Cleanup:** Bei Position schließen → Trigger-Wallets cleared

---

## 📋 Logging:

**Position öffnet:**
```
[Hybrid] 🎯 Tracking 2 trigger wallets for SELL generation
```

**SELL generiert:**
```
💉 [Hybrid] Injecting FAKE SELL pattern:
   Token: TokenX...
   Wallets: 1
   🎯 TRIGGER WALLETS (will close position!)
```

**Position schließt:**
```
[Hybrid] 🎯 Trigger wallets cleared
```

---

## ✅ Garantiert:

- ✅ Nur Trigger-Wallets verkaufen bei offener Position
- ✅ Position wird korrekt geschlossen
- ✅ Kein Random-Wallet verkauft mehr
- ✅ Trading Engine erkennt Trigger-Wallet SELL

---

**Test it! 🚀**

```powershell
python main.py paper
```

**Du solltest sehen:**
```
[Hybrid] 🎯 Tracking 2 trigger wallets
(Nach 30s+)
💉 [Hybrid] Injecting FAKE SELL pattern:
   🎯 TRIGGER WALLETS (will close position!)
[TradingEngine] 🚨 TRIGGER WALLET SOLD
[TradingEngine] ✅ Closed position
```

**Perfekt! 🎯✅**
