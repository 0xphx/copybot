import sys

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        from runners import help
        help.run()
        return

    mode = sys.argv[1]

    if mode == "import":
        import import_wallets  # liest axiom_wallets.json -> schreibt in axiom.db

    elif mode == "test":
        from runners import test_wallet_sync
        test_wallet_sync.run()

    elif mode == "simulate":
        from runners import test_observation
        test_observation.run()

    elif mode == "offline":
        from runners import offline
        offline.run()

    elif mode == "live":
        from runners import live
        live.run()

    elif mode == "hybrid":
        from runners import hybrid
        hybrid.run()

    elif mode == "paper":
        from runners import paper_trading
        import asyncio
        asyncio.run(paper_trading.main())

    elif mode == "paper_mainnet":
        from runners import paper_mainnet
        import asyncio
        asyncio.run(paper_mainnet.main())

    elif mode == "wallet_analysis":
        from runners import wallet_analysis
        import asyncio
        asyncio.run(wallet_analysis.main())

    elif mode == "show_wallets":
        from runners import show_wallets
        show_wallets.run()

    elif mode == "evaluate_wallets":
        from runners import evaluate_wallets
        evaluate_wallets.run()

    elif mode == "tune_observer":
        from runners import tune_observer
        tune_observer.run(sys.argv[2:])

    elif mode == "show_db":
        from runners import show_db
        show_db.run(sys.argv[2:])

    elif mode == "logs":
        from runners import logs
        logs.run(sys.argv[2:])

    elif mode == "list":
        from runners import wallet_list
        wallet_list.run(sys.argv[2:])

    elif mode == "keys":
        from runners import keys
        keys.run(sys.argv[2:])

    elif mode == "live_log":
        from runners import live_log
        live_log.run(sys.argv[2:])

    elif mode == "scann_all":
        from runners import scann_all
        scann_all.run()

    elif mode == "live_polling":
        from runners import live_polling
        live_polling.run()

    elif mode == "live_rpc":
        from runners import live_rpc
        live_rpc.run()

    elif mode == "test_network":
        from runners import test_network
        test_network.run()

    elif mode == "connection_monitor":
        from runners import connection_monitor
        connection_monitor.run()

    elif mode == "network_debug":
        import network_debug

    else:
        print(f"\n Unbekannter Command: '{mode}'")
        print("   Tippe 'python main.py help' für alle verfügbaren Commands.\n")

if __name__ == "__main__":
    main()
