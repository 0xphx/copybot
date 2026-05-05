# Trade Log Viewer

Standalone-Tool zum Visualisieren von Copybot-JSON-Logs auf einer Coin-Chart.

Es ist ein **eigenes Tool im Copybot-Repo**, aber nicht in den Bot selbst integriert. Du kannst es mit beliebigen
`paper_trading_*.json` oder `paper_mainnet_*.json` Dateien verwenden.

## Features

- Liest Copybot-Session-JSONs
- Holt OHLCV-Candles von GeckoTerminal
- Konvertiert alles in **eine einzige Anzeige-Währung**
- Nutzt historische USD/EUR-Tageskurse über Frankfurter/ECB
- Startet direkt im Trade-Zeitraum
- Buttons für Trade Focus, Full History, Buy Cluster, Sell Cluster
- Marker liegen auf dem Chart-Preis, damit die Candles nicht verzerrt werden

## Nutzung

```bash
cd /Users/jakob/Documents/GitHub/copybot/trade-log-viewer

python3 viewer.py \
  /Users/jakob/Documents/GitHub/copybot/bot/data/paper_mainnet_20260207_005449.json \
  --token 7wqfc2zgutheTyFk3aEVT48ycfVyLfqM9qQDnzc1pump
```

## Dashboard mit automatischer Einspeisung

Das Dashboard scannt automatisch die Copybot-Logdateien und zeigt dir eine Liste
aller vergangenen Trade-Gruppen. Charts werden beim Klick erzeugt.

```bash
cd /Users/jakob/Documents/GitHub/copybot/trade-log-viewer

python3 serve.py --open
```

Standardquelle:

```text
/Users/jakob/Documents/GitHub/copybot/bot/data
```

Andere Quelle:

```bash
python3 serve.py --source-dir /pfad/zu/deinen/jsons --open
```

Mit Browser öffnen:

```bash
python3 viewer.py \
  /Users/jakob/Documents/GitHub/copybot/bot/data/paper_mainnet_20260207_005449.json \
  --token 7wqfc2zgutheTyFk3aEVT48ycfVyLfqM9qQDnzc1pump \
  --open
```

Alle Tokens einer Session rendern:

```bash
python3 viewer.py \
  /Users/jakob/Documents/GitHub/copybot/bot/data/paper_mainnet_20260207_005449.json \
  --all-tokens
```

Anzeige-Währung auf USD stellen:

```bash
python3 viewer.py \
  /Users/jakob/Documents/GitHub/copybot/bot/data/paper_mainnet_20260207_005449.json \
  --token 7wqfc2zgutheTyFk3aEVT48ycfVyLfqM9qQDnzc1pump \
  --display-currency USD
```

## Hinweis

- GeckoTerminal liefert Candles in USD.
- Deine Copybot-Logs speichern Preise derzeit als EUR.
- Das Tool rechnet deshalb alles sauber in eine gemeinsame Anzeige-Währung um.
- Die Marker werden trotzdem auf den echten Chart-Preis gesetzt, damit die Y-Achse
  nicht kaputtgeht, falls Log-Preis und Marktpreis auseinanderlaufen.
- Im Chart kannst du X- und Y-Achse separat enger oder weiter stellen.
