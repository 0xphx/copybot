import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [command] [options]")
        print()
        print("Commands:")
        print("  import                 - Import wallets from JSON to database")
        print("  test                   - Test wallet sync")
        print("  simulate               - Simulate trades with fake data")
        print("  offline                - Offline trade simulator (no network needed)")
        print("  live                   - Start Helius webhook listener")
        print("  live_polling [network] - Start POLLING listener (RECOMMENDED)")
        print("  live_rpc [network]     - Start RPC listener (deprecated - doesn't work)")
        print("  scann_all [network]    - Scan all Solana transactions")
        print("  test_network           - Test network connectivity")
        print("  network_debug          - Advanced network diagnostics")
        print()
        print("Examples:")
        print("  python main.py offline               # Works without internet!")
        print("  python main.py network_debug         # Diagnose connection issues")
        print("  python main.py live_rpc              # Use devnet (default)")
        print("  python main.py live_rpc mainnet      # Use mainnet")
        print("  python main.py scann_all devnet      # Scan devnet")
        print("  python main.py test_network          # Test all networks")
        return

    mode = sys.argv[1]

    if mode == "import":
        from runners import import_axiom
        import_axiom.run()

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
    
    elif mode == "network_debug":
        import network_debug
        # Script wird direkt ausgeführt

    else:
        print(f"Unknown mode: {mode}")
        print("Run 'python main.py' without arguments to see available commands")

if __name__ == "__main__":
    main()
