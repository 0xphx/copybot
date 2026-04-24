# Copybot – Git & Sync Workflow

## Zwei getrennte Systeme

| System | Tool | Überträgt | Wann |
|--------|------|-----------|------|
| **Git** | `git push/pull` | Code (.py, config) | Bei Code-Änderungen |
| **Deploy/Sync** | `deploy.py` | Datenbanken (.db) | Nach jeder Session |

Die DBs sind bewusst **nicht** in Git – sie sind binär, groß und nicht mergebar.

---

## Typischer Workflow

### Du entwickelst neuen Code auf dem PC:
```
1. git add . && git commit -m "..." && git push
2. python deploy.py update   <- Server holt neuen Code (git pull + pip install)
```

### Du startest eine Session:
```
# Auf PC:
cd bot && python main.py wallet_analysis
# -> Auto-Sync läuft nach Session-Ende automatisch

# Auf Server (via SSH + screen):
cd ~/copybot/bot && python3 main.py wallet_analysis
# -> Auto-Sync läuft nach Session-Ende automatisch
```

### Manueller DB-Sync (z.B. nach langer Pause):
```
python deploy.py sync
```

---

## Was in Git landet / nicht landet

```
copybot/
├── bot/                    ← IN GIT (Code)
│   ├── runners/
│   ├── observation/
│   ├── config/
│   └── data/
│       ├── *.db            ← NICHT in Git (.gitignore)
│       └── *.json          ← NICHT in Git (.gitignore)
├── deploy.py               ← IN GIT
├── .devices.json           ← NICHT in Git (Server-IPs, privat!)
├── .sync_tmp/              ← NICHT in Git (temporär)
└── .env                    ← NICHT in Git (API Keys!)
```

---

## Kollisions-Szenarien und wie sie gelöst sind

| Szenario | Problem | Lösung |
|----------|---------|--------|
| Beide Geräte haben neue DB-Sessions | Binär-Konflikt | Deploy-Sync merged auf SQL-Ebene |
| Server hat alten Code | git pull vergessen | `python deploy.py update` |
| `.devices.json` in Git | Server-IP öffentlich | In .gitignore eingetragen |
| Zwei Sync-Systeme | `sync_db.py` vs `deploy.py` | `sync_db.py` ist veraltet, nur `deploy.py` nutzen |
