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
# MULTI-KEY MODUS: Mehrere Helius API Keys rotieren
# Jeder Key hat 100k Credits/Tag -> 3 Keys = 300k/Tag
# Neue Keys erstellen: https://dev.helius.xyz/dashboard
# Format: nur den Key eintragen, NICHT die volle URL
# ============================================================

HELIUS_API_KEYS = [
    "f607043d-baf5-4bcb-bd7e-c9fca54c5cff",  # Key 1
    "c8ff413d-e106-42f2-8f83-ec7de75180df",  # Key 2
    "5c2e4c4f-7c06-4bfd-9fa7-8c9a4bbef8c1",  # Key 3
    "d1f7153b-9bb1-4283-bf3b-ee2c2447d2a1",  # Key 4
    "89c132ab-4c3b-44f2-9dd1-2a097aa2dddf",  # Key 5
    "d4b8cabd-de8b-456b-81d3-24194ad0d174",  # Key 6
    "8b8dd092-2619-4221-bd5a-2ed9856794fd",  # Key 7
]

# Daraus generierte Endpunkte (automatisch, nicht manuell aendern)
HELIUS_HTTP_ENDPOINTS = [
    f"https://mainnet.helius-rpc.com/?api-key={key}"
    for key in HELIUS_API_KEYS
]

# Fallback: Public RPCs wenn alle Helius-Keys erschoepft
# Werden automatisch ans Ende der Rotation gehaengt
PUBLIC_FALLBACK_ENDPOINTS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com",
    "https://solana.drpc.org",
]

# Fuer Kompatibilitaet mit altem Code
WS_ENDPOINTS = {
    NETWORK_MAINNET: "wss://api.mainnet-beta.solana.com",
    NETWORK_DEVNET:  "wss://api.devnet.solana.com",
    NETWORK_TESTNET: "wss://api.testnet.solana.com",
    NETWORK_LOCAL:   "ws://localhost:8900",
}
WS_HTTP_ENDPOINTS = {
    NETWORK_MAINNET: HELIUS_HTTP_ENDPOINTS[0] if HELIUS_HTTP_ENDPOINTS else "https://api.mainnet-beta.solana.com",
    NETWORK_DEVNET:  "https://api.devnet.solana.com",
    NETWORK_TESTNET: "https://api.testnet.solana.com",
    NETWORK_LOCAL:   "http://localhost:8899",
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
