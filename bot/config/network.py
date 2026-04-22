"""
Network Configuration fuer Copybot
Unterstuetzt zwei Polling-Modi:
  [P] Polling   - Helius HTTP RPC (bisheriges System, Credit-basiert)
  [W] WebSocket - Public Solana WS RPC (neues System, keine Credits)
"""

NETWORK_MAINNET = "mainnet"
NETWORK_DEVNET  = "devnet"
NETWORK_TESTNET = "testnet"
NETWORK_LOCAL   = "local"

# ============================================================
# POLLING MODUS: Helius HTTP Endpunkte
# ============================================================

RPC_HTTP_ENDPOINTS = {
    NETWORK_MAINNET: "https://mainnet.helius-rpc.com/?api-key=f607043d-baf5-4bcb-bd7e-c9fca54c5cff",
    NETWORK_DEVNET:  "https://devnet.helius-rpc.com",
    NETWORK_TESTNET: "https://api.testnet.solana.com",
    NETWORK_LOCAL:   "http://localhost:8899",
}

# ============================================================
# WEBSOCKET MODUS: Kostenlose Public Endpunkte (kein API-Key)
# ============================================================

# WebSocket URLs fuer logsSubscribe
WS_ENDPOINTS = {
    NETWORK_MAINNET: "wss://api.mainnet-beta.solana.com",
    NETWORK_DEVNET:  "wss://api.devnet.solana.com",
    NETWORK_TESTNET: "wss://api.testnet.solana.com",
    NETWORK_LOCAL:   "ws://localhost:8900",
}

# HTTP URLs fuer getTransaction (nach WS-Notification)
WS_HTTP_ENDPOINTS = {
    NETWORK_MAINNET: "https://api.mainnet-beta.solana.com",
    NETWORK_DEVNET:  "https://api.devnet.solana.com",
    NETWORK_TESTNET: "https://api.testnet.solana.com",
    NETWORK_LOCAL:   "http://localhost:8899",
}

# Alternative kostenlose HTTP Endpunkte (Fallback / Rotation)
WS_HTTP_FALLBACKS = {
    NETWORK_MAINNET: [
        "https://api.mainnet-beta.solana.com",
        "https://solana-api.projectserum.com",
    ],
}

# ============================================================
# LEGACY WebSocket URLs (alt, veraltet)
# ============================================================
RPC_ENDPOINTS = {
    NETWORK_MAINNET: "wss://mainnet.helius-rpc.com/?api-key=f607043d-baf5-4bcb-bd7e-c9fca54c5cff",
    NETWORK_DEVNET:  "wss://devnet.helius-rpc.com",
    NETWORK_TESTNET: "wss://api.testnet.solana.com",
    NETWORK_LOCAL:   "ws://localhost:8900",
}

DEFAULT_NETWORK = NETWORK_MAINNET


def get_rpc_url(network: str = None) -> str:
    """Gibt Helius WebSocket URL zurueck (legacy)"""
    if network is None:
        network = DEFAULT_NETWORK
    url = RPC_ENDPOINTS.get(network)
    if not url:
        raise ValueError(f"Unknown network: {network}")
    return url


def get_http_url(network: str = None) -> str:
    """Gibt Helius HTTP URL fuer Polling zurueck"""
    if network is None:
        network = DEFAULT_NETWORK
    url = RPC_HTTP_ENDPOINTS.get(network)
    if not url:
        raise ValueError(f"Unknown network: {network}")
    return url


def get_ws_url(network: str = None) -> str:
    """Gibt Public WebSocket URL fuer logsSubscribe zurueck"""
    if network is None:
        network = DEFAULT_NETWORK
    url = WS_ENDPOINTS.get(network)
    if not url:
        raise ValueError(f"Unknown network: {network}")
    return url


def get_ws_http_url(network: str = None) -> str:
    """Gibt Public HTTP URL fuer getTransaction (nach WS-Event) zurueck"""
    if network is None:
        network = DEFAULT_NETWORK
    url = WS_HTTP_ENDPOINTS.get(network)
    if not url:
        raise ValueError(f"Unknown network: {network}")
    return url
