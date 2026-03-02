"""
Help Runner - Zeigt alle verfügbaren Commands mit Beschreibung
"""


COMMANDS = [
    {
        "category": "🤖 PAPER TRADING",
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
        "category": "🔍 WALLET ANALYSE",
        "commands": [
            {
                "cmd": "wallet_analysis",
                "args": "",
                "desc": "Jedes Wallet unabhängig analysieren + Confidence DB befüllen",
                "details": [
                    "Jedes Wallet bekommt ein eigenes virtuelles Konto (1000 EUR, 20% pro Trade)",
                    "Jeder BUY öffnet eine Position für genau dieses Wallet",
                    "Jeder SELL schließt die Position und berechnet P&L",
                    "Ergebnisse werden in data/wallet_performance.db gespeichert",
                    "Confidence Score wird pro Wallet berechnet (Win-Rate, P&L, Trade-Anzahl)",
                    "Je mehr Sessions, desto genauer werden die Scores",
                ],
            },
            {
                "cmd": "show_db",
                "args": "[sort] [--min N] [sessions] [wallet PREFIX]",
                "desc": "Wallet Datenbank im Terminal anzeigen",
                "details": [
                    "show_db                 → Alle Wallets nach Confidence sortiert",
                    "show_db pnl             → Sortiert nach Total P&L",
                    "show_db winrate         → Sortiert nach Win-Rate",
                    "show_db trades          → Sortiert nach Trade-Anzahl",
                    "show_db --min 5         → Nur Wallets mit mindestens 5 Trades",
                    "show_db sessions        → Alle Sessions mit Datum und Stats",
                    "show_db wallet 3LUfv2  → Detail-Ansicht eines Wallets (Prefix reicht)",
                ],
            },
        ],
    },
    {
        "category": "🌐 LIVE / MONITORING",
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
        "category": "🗄️  DATEN & WALLETS",
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
        "category": "🛠️  ENTWICKLUNG & DEBUGGING",
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
    print("  COPYBOT  –  HELP")
    print("  " + "═" * (W - 2))
    print()
    print("  Usage:  python main.py <command> [options]")
    print()

    for section in COMMANDS:
        print()
        print(f"  {section['category']}")
        print("  " + "─" * (W - 2))

        for entry in section["commands"]:
            args_str = f" {entry['args']}" if entry['args'] else ""
            cmd_line = f"python main.py {entry['cmd']}{args_str}"

            print(f"  \033[1m{cmd_line}\033[0m")
            print(f"    → {entry['desc']}")

            for detail in entry.get("details", []):
                print(f"       • {detail}")

            print()

    print("─" * W)
    print()
