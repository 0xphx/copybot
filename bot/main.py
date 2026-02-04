import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [import|test|simulate|live|live_rpc]")
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

    elif mode == "live":
        from runners import live
        live.run()

    elif mode == "live_rpc":
        from runners import live_rpc
        live_rpc.run()

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
