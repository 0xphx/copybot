"""
Network Configuration für Copybot - WITH HELIUS
Mit Premium RPC Provider für bessere Performance
"""

# Netzwerk-Modi
NETWORK_MAINNET = "mainnet"
NETWORK_DEVNET = "devnet"
NETWORK_TESTNET = "testnet"
NETWORK_LOCAL = "local"

# ============================================================
# RPC ENDPOINTS mit Helius Integration
# ============================================================

# WebSocket URLs (für alte logsSubscribe - funktioniert nicht mehr)
RPC_ENDPOINTS = {
    NETWORK_MAINNET: "wss://mainnet.helius-rpc.com/?api-key=f607043d-baf5-4bcb-bd7e-c9fca54c5cff",
    NETWORK_DEVNET: "wss://devnet.helius-rpc.com",
    NETWORK_TESTNET: "wss://api.testnet.solana.com",
    NETWORK_LOCAL: "ws://localhost:8900",
}

# HTTP URLs (für Polling - funktioniert!)
RPC_HTTP_ENDPOINTS = {
    NETWORK_MAINNET: "https://mainnet.helius-rpc.com/?api-key=f607043d-baf5-4bcb-bd7e-c9fca54c5cff",
    NETWORK_DEVNET: "https://devnet.helius-rpc.com",
    NETWORK_TESTNET: "https://api.testnet.solana.com",
    NETWORK_LOCAL: "http://localhost:8899",
}

# ============================================================
# FALLBACK ENDPOINTS (für Reference)
# ============================================================
FALLBACK_ENDPOINTS = {
    # Solana Public RPC (als Fallback, hat aber Limits)
    "public_mainnet": "wss://api.mainnet-beta.solana.com",
    "public_devnet": "wss://api.devnet.solana.com",
}

# Standard-Netzwerk
DEFAULT_NETWORK = NETWORK_DEVNET

def get_rpc_url(network: str = None) -> str:
    """Gibt WebSocket URL (deprecated - use get_http_url for polling)"""
    if network is None:
        network = DEFAULT_NETWORK
    url = RPC_ENDPOINTS.get(network)
    if not url:
        raise ValueError(f"Unknown network: {network}")
    return url

def get_http_url(network: str = None) -> str:
    """Gibt HTTP URL für Polling zurück"""
    if network is None:
        network = DEFAULT_NETWORK
    url = RPC_HTTP_ENDPOINTS.get(network)
    if not url:
        raise ValueError(f"Unknown network: {network}")
    return url

def get_all_endpoints(network: str = None) -> list[str]:
    """Gibt alle verfügbaren Endpoints für ein Netzwerk zurück"""
    if network is None:
        network = DEFAULT_NETWORK
    
    return [RPC_ENDPOINTS.get(network)]

def print_network_info(network: str = None, show_alternatives: bool = False):
    """Zeigt Info über das verwendete Netzwerk"""
    if network is None:
        network = DEFAULT_NETWORK
    
    url = get_rpc_url(network)
    
    print(f"[Network] Using {network.upper()}")
    
    # Mask API key in output
    display_url = url.replace("f607043d-baf5-4bcb-bd7e-c9fca54c5cff", "***API_KEY***")
    print(f"[Network] RPC: {display_url}")
    
    if network == NETWORK_DEVNET:
        print("[Network] [INFO]  Devnet - Test environment with airdropped SOL")
        print("[Network] [INFO] Using Helius RPC (Free Tier)")
    elif network == NETWORK_MAINNET:
        print("[Network] [WARNING]  Mainnet - Real money, real trades!")
        print("[Network] [INFO] Using Helius RPC (Enhanced features)")
    elif network == NETWORK_TESTNET:
        print("[Network] [INFO]  Testnet - Experimental test environment")
    elif network == NETWORK_LOCAL:
        print("[Network] [OFFLINE] Local validator")

def print_helius_info():
    """Zeigt Info über Helius RPC"""
    print("\n[OK] HELIUS RPC CONFIGURED!")
    print("   Benefits:")
    print("   • Wallet subscriptions supported")
    print("   • Higher rate limits (100k requests/day)")
    print("   • Better reliability")
    print("   • Enhanced transaction data")
    print("   • Free tier for development")
