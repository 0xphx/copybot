"""
Wallet Activity Scanner - Zeigt welche Wallets in letzter Zeit aktiv waren
"""
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict
import sys
import os

# Füge parent directory zu path hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.network import RPC_HTTP_ENDPOINTS, NETWORK_MAINNET
from wallets.sync import sync_wallets


class WalletActivityScanner:
    """Scannt Wallet-Aktivität"""
    
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.session = None
    
    async def check_wallet_activity(
        self, 
        wallet: str, 
        hours_back: int = 1
    ) -> Dict:
        """
        Prüft ob Wallet in den letzten X Stunden aktiv war
        
        Returns:
            {
                'wallet': str,
                'active': bool,
                'tx_count': int,
                'latest_tx_time': datetime or None
            }
        """
        try:
            # Hole letzte Signatures
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    wallet,
                    {"limit": 10}  # Letzte 10 TXs
                ]
            }
            
            async with self.session.post(
                self.rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                data = await response.json()
                
                if "error" in data:
                    return {
                        'wallet': wallet,
                        'active': False,
                        'tx_count': 0,
                        'latest_tx_time': None,
                        'error': data['error']
                    }
                
                signatures = data.get("result", [])
                
                if not signatures:
                    return {
                        'wallet': wallet,
                        'active': False,
                        'tx_count': 0,
                        'latest_tx_time': None
                    }
                
                # Prüfe Zeitstempel
                now = datetime.now()
                cutoff = now - timedelta(hours=hours_back)
                
                recent_txs = []
                latest_time = None
                
                for sig_info in signatures:
                    block_time = sig_info.get("blockTime")
                    if block_time:
                        tx_time = datetime.fromtimestamp(block_time)
                        
                        if not latest_time:
                            latest_time = tx_time
                        
                        if tx_time >= cutoff:
                            recent_txs.append(sig_info)
                
                return {
                    'wallet': wallet,
                    'active': len(recent_txs) > 0,
                    'tx_count': len(recent_txs),
                    'latest_tx_time': latest_time,
                    'total_checked': len(signatures)
                }
                
        except asyncio.TimeoutError:
            return {
                'wallet': wallet,
                'active': False,
                'tx_count': 0,
                'latest_tx_time': None,
                'error': 'timeout'
            }
        except Exception as e:
            return {
                'wallet': wallet,
                'active': False,
                'tx_count': 0,
                'latest_tx_time': None,
                'error': str(e)
            }
    
    async def scan_all_wallets(
        self, 
        wallets: List[str], 
        hours_back: int = 1
    ) -> List[Dict]:
        """Scannt alle Wallets parallel"""
        
        self.session = aiohttp.ClientSession()
        
        try:
            print(f"\n🔍 Scanning {len(wallets)} wallets for activity in last {hours_back} hour(s)...")
            print("This may take a moment...\n")
            
            # Parallel scannen
            tasks = [
                self.check_wallet_activity(wallet, hours_back) 
                for wallet in wallets
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter Exceptions
            valid_results = []
            for result in results:
                if isinstance(result, Exception):
                    print(f"❌ Error: {result}")
                else:
                    valid_results.append(result)
            
            return valid_results
            
        finally:
            await self.session.close()


def print_results(results: List[Dict], hours_back: int):
    """Zeigt Ergebnisse schön formatiert"""
    
    # Sortiere nach Aktivität
    active = [r for r in results if r['active']]
    inactive = [r for r in results if not r['active']]
    
    print("="*70)
    print(f"📊 WALLET ACTIVITY REPORT (Last {hours_back} hour(s))")
    print("="*70)
    print()
    
    print(f"✅ Active Wallets:  {len(active)}/{len(results)}")
    print(f"❌ Inactive Wallets: {len(inactive)}/{len(results)}")
    print()
    
    if active:
        print("="*70)
        print("🟢 ACTIVE WALLETS")
        print("="*70)
        
        # Sortiere nach Anzahl TXs
        active.sort(key=lambda x: x['tx_count'], reverse=True)
        
        for result in active:
            wallet = result['wallet']
            tx_count = result['tx_count']
            latest = result['latest_tx_time']
            
            if latest:
                time_ago = datetime.now() - latest
                minutes_ago = int(time_ago.total_seconds() / 60)
                
                if minutes_ago < 60:
                    time_str = f"{minutes_ago}m ago"
                else:
                    hours_ago = minutes_ago // 60
                    time_str = f"{hours_ago}h ago"
            else:
                time_str = "unknown"
            
            print(f"🟢 {wallet[:8]}... | {tx_count} TXs | Latest: {time_str}")
    
    if inactive:
        print()
        print("="*70)
        print(f"⚪ INACTIVE WALLETS (No activity in last {hours_back}h)")
        print("="*70)
        
        for result in inactive:
            wallet = result['wallet']
            latest = result['latest_tx_time']
            
            if latest:
                time_ago = datetime.now() - latest
                hours_ago = int(time_ago.total_seconds() / 3600)
                
                if hours_ago < 24:
                    time_str = f"{hours_ago}h ago"
                else:
                    days_ago = hours_ago // 24
                    time_str = f"{days_ago}d ago"
            else:
                time_str = "never"
            
            print(f"⚪ {wallet[:8]}... | Last activity: {time_str}")
    
    print()
    print("="*70)
    
    # Empfehlungen
    if len(active) < len(results) * 0.3:  # Weniger als 30% aktiv
        print("\n⚠️  LOW ACTIVITY WARNING")
        print(f"   Only {len(active)}/{len(results)} wallets are active.")
        print("   Consider:")
        print("   - Waiting for more activity")
        print("   - Adding more active wallets")
        print("   - Using paper mode (hybrid) for testing")
    elif len(active) >= len(results) * 0.5:  # 50%+ aktiv
        print("\n✅ GOOD ACTIVITY")
        print(f"   {len(active)}/{len(results)} wallets are trading.")
        print("   Good time to start paper_mainnet mode!")


async def main():
    """Entry Point"""
    
    print("="*70)
    print("🔍 WALLET ACTIVITY SCANNER")
    print("="*70)
    print()
    
    # Lade Wallets
    wallets = sync_wallets()
    if not wallets:
        print("❌ No wallets found in database!")
        return
    
    wallet_addresses = [w.wallet for w in wallets]
    print(f"Loaded {len(wallet_addresses)} wallets from database")
    
    # Frage Zeitfenster
    print("\nHow far back to check?")
    print("  1 - Last 1 hour")
    print("  2 - Last 2 hours")
    print("  3 - Last 6 hours")
    print("  4 - Last 24 hours")
    
    choice = input("\nChoice (default=1): ").strip() or "1"
    
    hours_map = {
        "1": 1,
        "2": 2,
        "3": 6,
        "4": 24
    }
    
    hours_back = hours_map.get(choice, 1)
    
    # Scanne
    scanner = WalletActivityScanner(RPC_HTTP_ENDPOINTS[NETWORK_MAINNET])
    results = await scanner.scan_all_wallets(wallet_addresses, hours_back)
    
    # Zeige Ergebnisse
    print_results(results, hours_back)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
