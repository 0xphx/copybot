# 🔧 SOFTLOCK FIX - SELL Signals bleiben aktiv!

**Datum:** 06.02.2026

---

## 🚨 Problem: Softlock!

**Vorher:**
```
Position öffnet → Fake Trades pausiert
→ Keine BUYs ✅
→ Keine SELLs ❌ (PROBLEM!)
→ Position kann nie geschlossen werden
→ SOFTLOCK! 🔒
```

---

## ✅ Lösung: Separiere BUY und SELL Tasks

### Neue Architektur:

**3 parallele Tasks:**

```python
Task 1: Real Polling (Mainnet)
Task 2: Fake BUY Generator    ← Kann pausiert werden
Task 3: Fake SELL Generator   ← Läuft IMMER!
```

### Task 2: Fake BUY Generator
```python
async def _inject_fake_buys(self):
    while self.running:
        # Pausierbar!
        if self.pause_fake_injector:
            await asyncio.sleep(1)
            continue
        
        # Generiere BUY Pattern
        await self._generate_fake_buy_pattern()
        await asyncio.sleep(20)  # Alle 20s
```

### Task 3: Fake SELL Generator  
```python
async def _inject_fake_sells(self):
    await asyncio.sleep(35)  # Erste SELLs nach 35s
    
    while self.running:
        # IMMER aktiv, nicht pausierbar!
        if self.fake_buy_trades:
            await self._generate_fake_sell_if_old()
        
        await asyncio.sleep(5)  # Prüfe alle 5s
```

---

## 🔄 Workflow jetzt:

### 1. Normal Mode:
```
[BUY Task]  → Generiert BUYs alle 20s
[SELL Task] → Prüft alte BUYs alle 5s
```

### 2. Position öffnet:
```
[Hybrid] ⏸️ Fake trade injector PAUSED

[BUY Task]  → PAUSIERT ❌
[SELL Task] → Läuft weiter! ✅
```

### 3. SELL kommt (nach 30s+):
```
💉 [Hybrid] Injecting FAKE SELL pattern
[TradingEngine] Position closed
```

### 4. Position schließt:
```
[Hybrid] ▶️ Fake trade injector RESUMED

[BUY Task]  → Wieder aktiv ✅
[SELL Task] → Läuft weiter ✅
```

---

## 🎯 Fixes im Detail:

### Fix 1: BUY Pattern Interrupt
```python
for i, wallet in enumerate(selected_wallets):
    # Prüfe ob pausiert wurde
    if self.pause_fake_injector:
        logger.info(f"[Hybrid] ⚠️ BUY pattern INTERRUPTED after {i} trades")
        break  # Stoppe sofort!
    
    # Generiere Trade...
```

**Verhindert:** 3. Wallet wird nicht mehr emitted wenn schon pausiert!

### Fix 2: Separate SELL Task
```python
# Läuft parallel, unabhängig vom BUY Generator
async def _inject_fake_sells(self):
    while self.running:
        # KEINE Pause-Prüfung!
        if self.fake_buy_trades:
            await self._generate_fake_sell_if_old()
        await asyncio.sleep(5)
```

**Verhindert:** Softlock - SELLs kommen immer!

---

## 📊 Erwartetes Verhalten:

```
00:00 - Start
00:05 - BUY Pattern (2 Wallets) → Position öffnet
        [Hybrid] ⏸️ Fake trade injector PAUSED
        
00:10 - (BUY Task pausiert, keine neuen BUYs)
00:15 - (SELL Task läuft weiter)
00:20 - (SELL Task läuft weiter)
00:25 - (SELL Task läuft weiter)
00:30 - (SELL Task läuft weiter)
00:35 - SELL Pattern! → Position schließt ✅
        [Hybrid] ▶️ Fake trade injector RESUMED
        
00:55 - Nächstes BUY Pattern
```

---

## ⚙️ Timing:

- **BUY Interval:** 20 Sekunden
- **SELL Check:** Alle 5 Sekunden
- **SELL Trigger:** Wenn BUY älter als 30 Sekunden
- **Erste SELL:** Nach 35 Sekunden (5s + 30s)

---

## ✅ Kein Softlock mehr!

**Vorher:**
- Position offen → Alles pausiert → Softlock 🔒

**Jetzt:**
- Position offen → Nur BUYs pausiert → SELLs kommen weiter → Exit möglich ✅

---

**Test it! 🚀**

```powershell
python main.py paper
```

**Du solltest sehen:**
```
[Hybrid] ⏸️ Fake trade injector PAUSED
(Nach 30s+)
💉 [Hybrid] Injecting FAKE SELL pattern
[TradingEngine] ✅ Closed position
[Hybrid] ▶️ Fake trade injector RESUMED
```

**Kein Softlock mehr! 🎉**
