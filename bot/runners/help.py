"""
Help Runner - Zeigt alle verfügbaren Commands mit Beschreibung
"""


COMMANDS = [
    {
        "category": " PAPER TRADING",
        "commands": [
            {
                "cmd": "paper_mainnet",
                "args": "",
                "desc": "Paper Trading auf echtem Mainnet",
                "details": [
                    "Beobachtet echte Solana Transaktionen",
                    "Interaktive Konfiguration beim Start (Kapital, SL/TP, etc.)",
                    "Öffnet/schließt virtuelle Positionen basierend auf Wallet-Signalen",
                    "Nutzt historische Confidence Scores aus der DB (falls vorhanden)",
                    "Live P&L Tracking + Stop-Loss / Take-Profit Automatik",
                ],
            },
            {
                "cmd": "paper",
                "args": "",
                "desc": "Paper Trading im Hybrid-Modus (Mainnet + Fake Trades)",
                "details": [
                    "Wie paper_mainnet, aber füllt ruhige Phasen mit simulierten Trades",
                    "Gut zum Testen der Engine ohne auf echte Trades zu warten",
                ],
            },
        ],
    },
    {
        "category": " OPTIMIERUNG",
        "commands": [
            {
                "cmd": "tune_observer",
                "args": "[--sessions N] [--top N]",
                "desc": "Hyperparameter-Simulation auf Observer-Daten",
                "details": [
                    "Testet alle Kombinationen von Stagnation + MaxHold",
                    "Stagnation: 5/10/15/20/30 Min",
                    "MaxHold:    20/40/60/90/120 Min",
                    "Berechnet EV, WR, PnL fuer jede Kombination",
                    "Gibt Heatmap + Ranking der besten Konfiguration aus",
                    "--sessions 3   nur letzte 3 Sessions verwenden",
                    "--top 5        nur Top 5 Kombinationen anzeigen",
                ],
            },
            {
                "cmd": "evaluate_wallets",
                "args": "",
                "desc": "CandidateWallets mit ActiveWallets vergleichen (EV-basiert)",
                "details": [
                    "Berechnet EV aus observer_performance.db",
                    "Mindest-Trades: 20 pro Wallet",
                    "Candidates mit hoeherem EV ersetzen schlechteste Actives",
                    "Ersetzte Actives -> ArchivedWallet",
                ],
            },
        ],
    },
    {
        "category": " WALLET ANALYSE",
        "commands": [
            {
                "cmd": "wallet_analysis",
                "args": "",
                "desc": "Wallet Analyse starten (Modus waehlbar beim Start)",
                "details": [
                    "[1] Analysis Mode:  Eigener SL/TP, misst Bot-Performance",
                    "      Jedes Wallet bekommt 1000 EUR, 20% pro Trade",
                    "      -> Speichert in data/wallet_performance.db",
                    "[2] Observer Mode:  Folgt Wallet 1:1 (kein SL/TP)",
                    "      Misst echtes Wallet-Verhalten + High/Low Tracking",
                    "      Stagnation-Timeout: 30 Min kein Preischange -> schliessen",
                    "      Max-Haltedauer: 60 Min -> schliessen",
                    "      -> Speichert in data/observer_performance.db",
                ],
            },
            {
                "cmd": "show_wallets",
                "args": "",
                "desc": "Alle Wallets im Bot anzeigen (axiom.db)",
                "details": [
                    "Zeigt OwnWallet, ActiveWallets, CandidateWallets, ArchivedWallets",
                    "ActiveWallets mit Label [smart] oder [custom]",
                    "Inkl. Gesamtanzahl pro Kategorie",
                ],
            },
            {
                "cmd": "evaluate_wallets",
                "args": "",
                "desc": "CandidateWallets mit ActiveWallets vergleichen und ggf. tauschen",
                "details": [
                    "Berechnet EV (Expected Value) aus observer_performance.db",
                    "EV = WinRate * AvgWin - (1 - WinRate) * AvgLoss",
                    f"Mindest-Trades: 20 pro Wallet",
                    "Candidates mit hoeherem EV ersetzen schlechteste Actives",
                    "Ersetzte Actives -> ArchivedWallet (bleiben in DB)",
                    "Aenderung nur in axiom_wallets.json, danach import_wallets.py noetig",
                ],
            },
            {
                "cmd": "show_db",
                "args": "[--observer] [sort] [--min N] [sessions] [wallet PREFIX]",
                "desc": "Wallet Datenbank im Terminal anzeigen",
                "details": [
                    "show_db                      Analysis-DB (wallet_performance.db)",
                    "show_db --observer           Observer-DB (observer_performance.db)",
                    "show_db pnl                  Sortiert nach Total P&L",
                    "show_db winrate              Sortiert nach Win-Rate",
                    "show_db trades               Sortiert nach Trade-Anzahl",
                    "show_db --min 5              Nur Wallets mit mindestens 5 Trades",
                    "show_db sessions             Alle Sessions mit Datum und Stats",
                    "show_db wallet 3LUfv2        Detail-Ansicht eines Wallets (Prefix reicht)",
                    "show_db --observer sessions  Observer-Sessions anzeigen",
                ],
            },
        ],
    },
    {
        "category": "  DB WARTUNG",
        "commands": [
            {
                "cmd": "migrate_and_recalc.py",
                "args": "[--observer]",
                "desc": "DB-Schema migrieren + alle Wallet-Stats neu berechnen",
                "details": [
                    "python migrate_and_recalc.py            Analysis-DB",
                    "python migrate_and_recalc.py --observer Observer-DB",
                    "Fuegt fehlende Spalten hinzu (price_missing, strategy_label, etc.)",
                    "Berechnet Confidence Score, Label und dynamische SL/TP neu",
                    "Ausfuehren nach Code-Aenderungen an der Label/Score-Logik",
                ],
            },
            {
                "cmd": "cleanup_pre_sl_data.py",
                "args": "[--observer]",
                "desc": "Pre-SL Trades loeschen + Stats neu berechnen",
                "details": [
                    "python cleanup_pre_sl_data.py            Analysis-DB",
                    "python cleanup_pre_sl_data.py --observer Observer-DB",
                    "Loescht alle Trades vor 2026-03-03 (vor Stop-Loss Einfuehrung)",
                    "Berechnet alle Wallet-Stats danach neu",
                ],
            },
        ],
    },
    {
        "category": " LIVE / MONITORING",
        "commands": [
            {
                "cmd": "live_polling",
                "args": "[mainnet|devnet]",
                "desc": "Echte Transaktionen per Polling beobachten (empfohlen)",
                "details": [
                    "Pollt alle aktiven Wallets regelmäßig nach neuen Transaktionen",
                    "Standard: mainnet",
                ],
            },
            {
                "cmd": "live",
                "args": "",
                "desc": "Helius Webhook Listener starten",
                "details": [
                    "Empfängt Push-Benachrichtigungen via Helius Webhook",
                    "Benötigt konfigurierten Helius API Key",
                ],
            },
            {
                "cmd": "hybrid",
                "args": "",
                "desc": "Hybrid Modus: Mainnet Polling + simulierte Fake Trades",
                "details": [
                    "Kombiniert echte Mainnet Daten mit synthetischen Trades",
                    "Nur für Entwicklung und Tests",
                ],
            },
        ],
    },
    {
        "category": "  DATEN & WALLETS",
        "commands": [
            {
                "cmd": "import",
                "args": "",
                "desc": "Wallets aus JSON-Datei in die Datenbank importieren",
                "details": [
                    "Liest Wallets aus der Axiom-Export Datei",
                    "Speichert sie in data/axiom.db",
                ],
            },
            {
                "cmd": "test",
                "args": "",
                "desc": "Wallet Sync testen (zeigt geladene Wallets)",
                "details": [
                    "Lädt Wallets aus der DB und gibt sie aus",
                    "Gut zum Prüfen ob Import funktioniert hat",
                ],
            },
            {
                "cmd": "scann_all",
                "args": "[mainnet|devnet]",
                "desc": "Alle Solana Transaktionen der beobachteten Wallets scannen",
                "details": [],
            },
        ],
    },
    {
        "category": "  ENTWICKLUNG & DEBUGGING",
        "commands": [
            {
                "cmd": "offline",
                "args": "",
                "desc": "Offline Trade Simulator (kein Netzwerk nötig)",
                "details": [
                    "Simuliert Trades komplett lokal ohne RPC-Verbindung",
                    "Ideal zum Testen der Engine-Logik",
                ],
            },
            {
                "cmd": "simulate",
                "args": "",
                "desc": "Trade Simulation mit Fake-Daten",
                "details": [
                    "Generiert synthetische Trade Events und schickt sie durch die Engine",
                ],
            },
            {
                "cmd": "test_network",
                "args": "",
                "desc": "Netzwerk-Konnektivität zu allen RPC Endpoints testen",
                "details": [],
            },
            {
                "cmd": "network_debug",
                "args": "",
                "desc": "Erweiterte Netzwerk-Diagnose",
                "details": [
                    "Detaillierte Analyse von Verbindungsproblemen",
                    "Zeigt Latenz, Fehlerrate und RPC Status",
                ],
            },
        ],
    },
]


def run():
    W = 70

    print()
    print("  COPYBOT    HELP")
    print("  " + "" * (W - 2))
    print()
    print("  Usage:  python main.py <command> [options]")
    print()

    for section in COMMANDS:
        print()
        print(f"  {section['category']}")
        print("  " + "" * (W - 2))

        for entry in section["commands"]:
            args_str = f" {entry['args']}" if entry['args'] else ""
            cmd_line = f"python main.py {entry['cmd']}{args_str}"

            print(f"  \033[1m{cmd_line}\033[0m")
            print(f"     {entry['desc']}")

            for detail in entry.get("details", []):
                print(f"        {detail}")

            print()

    print("" * W)
    print()
