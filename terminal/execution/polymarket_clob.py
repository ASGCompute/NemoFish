"""
NemoFish Polymarket CLOB Client
================================
Direct API trading using EIP-712 signed orders.
No dependency on py-clob-client — uses raw eth_account + web3.

Polymarket CLOB flow:
  1. Derive API creds (L1 auth with private key → L2 API key/secret/passphrase)
  2. Sign order payload with EIP-712 (private key)
  3. Post signed order to CLOB REST API
  4. Track fills and positions

Docs: https://docs.polymarket.com/
CLOB: https://clob.polymarket.com
Chain: Polygon (137)
"""

import os
import json
import time
import hmac
import hashlib
import base64
import urllib.request
import urllib.error
from typing import Optional, Dict, List
from dataclasses import dataclass
from eth_account import Account
from eth_account.messages import encode_typed_data


# Constants
CLOB_BASE = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # Polymarket CTF Exchange
NEG_RISK_CTF_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


@dataclass
class OrderResult:
    success: bool
    order_id: str = ""
    error: str = ""
    details: dict = None


class PolymarketCLOB:
    """
    Direct Polymarket CLOB trader using private key + EIP-712 signing.
    
    Usage:
        clob = PolymarketCLOB(
            private_key="0x...",
            api_key="019cf588-...",  # Relayer API key
        )
        
        # Place a market buy order
        result = clob.market_buy(
            token_id="12345...",  # YES or NO outcome token
            amount=1.00,          # Amount in USD
        )
    """

    def __init__(
        self,
        private_key: str = None,
        api_key: str = None,
        api_secret: str = None,
        api_passphrase: str = None,
        funder: str = None,
    ):
        if private_key is None:
            private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
        if api_key is None:
            api_key = os.environ.get("POLYMARKET_API_KEY", "")
        
        self.private_key = private_key
        self.api_key = api_key
        self.api_secret = api_secret or os.environ.get("POLYMARKET_API_SECRET", "")
        self.api_passphrase = api_passphrase or os.environ.get("POLYMARKET_API_PASSPHRASE", "")
        
        # Derive wallet address from private key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.funder = funder or self.address
        
        # We need L2 auth for trading — derive if not provided
        if not self.api_secret:
            self._derive_api_credentials()

    def _fetch(self, url: str, method: str = "GET", data: dict = None, auth: bool = False) -> dict:
        """Make authenticated or unauthenticated request to CLOB API."""
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("User-Agent", "NemoFish-Terminal/1.0")
        req.add_header("Content-Type", "application/json")
        
        if auth and self.api_key:
            timestamp = str(int(time.time()))
            req.add_header("POLY_API_KEY", self.api_key)
            req.add_header("POLY_TIMESTAMP", timestamp)
            req.add_header("POLY_NONCE", str(int(time.time() * 1000)))
            
            if self.api_secret:
                # HMAC signature for L2 auth
                msg = timestamp + method + "/order"
                if body:
                    msg += body.decode()
                sig = hmac.new(
                    base64.b64decode(self.api_secret),
                    msg.encode(),
                    hashlib.sha256,
                ).digest()
                req.add_header("POLY_SIGNATURE", base64.b64encode(sig).decode())
                req.add_header("POLY_PASSPHRASE", self.api_passphrase)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            return {"error": f"HTTP {e.code}: {body[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def _derive_api_credentials(self):
        """
        Derive L2 API credentials from L1 private key.
        This creates API key + secret + passphrase for trading.
        """
        print("🔑 Deriving L2 API credentials...")
        
        # Sign a "create API key" message with EIP-712
        timestamp = str(int(time.time()))
        nonce = int(time.time() * 1000)
        
        # The derive-api-key endpoint uses L1 auth (private key signature)
        msg_to_sign = f"Sign in to Polymarket CLOB\nTimestamp: {timestamp}\nNonce: {nonce}"
        
        signed = self.account.sign_message(
            encode_typed_data(
                domain_data={
                    "name": "ClobAuthDomain",
                    "version": "1",
                    "chainId": CHAIN_ID,
                },
                message_types={
                    "ClobAuth": [
                        {"name": "address", "type": "address"},
                        {"name": "timestamp", "type": "string"},
                        {"name": "nonce", "type": "uint256"},
                        {"name": "message", "type": "string"},
                    ],
                },
                primary_type="ClobAuth",
                message_data={
                    "address": self.address,
                    "timestamp": timestamp,
                    "nonce": nonce,
                    "message": "This message attests that I control the given wallet",
                },
            )
        )
        
        # Post to derive-api-key endpoint
        result = self._fetch(
            f"{CLOB_BASE}/auth/derive-api-key",
            method="POST",
            data={
                "message": "This message attests that I control the given wallet",
                "timestamp": timestamp,
                "nonce": nonce,
                "signature": signed.signature.hex(),
            },
        )
        
        if "error" not in result:
            self.api_key = result.get("apiKey", self.api_key)
            self.api_secret = result.get("secret", "")
            self.api_passphrase = result.get("passphrase", "")
            print(f"  ✅ L2 credentials derived: key={self.api_key[:12]}...")
        else:
            print(f"  ⚠️ L2 derive failed: {result.get('error', '')[:100]}")
            print("  Falling back to Relayer API key mode")

    def get_server_time(self) -> int:
        """Get CLOB server timestamp."""
        result = self._fetch(f"{CLOB_BASE}/time")
        return int(result) if isinstance(result, (int, float, str)) and str(result).isdigit() else 0

    def get_order_book(self, token_id: str) -> dict:
        """Get order book for a specific outcome token."""
        return self._fetch(f"{CLOB_BASE}/book?token_id={token_id}")

    def get_price(self, token_id: str) -> float:
        """Get current best price for a token."""
        book = self.get_order_book(token_id)
        asks = book.get("asks", [])
        if asks:
            return float(asks[0].get("price", 0))
        return 0.0

    def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price."""
        result = self._fetch(f"{CLOB_BASE}/midpoint?token_id={token_id}")
        return float(result.get("mid", 0))

    def _sign_order(self, order: dict) -> str:
        """Sign an order using EIP-712."""
        signed = self.account.sign_message(
            encode_typed_data(
                domain_data={
                    "name": "Polymarket CTF Exchange",
                    "version": "1",
                    "chainId": CHAIN_ID,
                    "verifyingContract": CTF_EXCHANGE,
                },
                message_types={
                    "Order": [
                        {"name": "salt", "type": "uint256"},
                        {"name": "maker", "type": "address"},
                        {"name": "signer", "type": "address"},
                        {"name": "taker", "type": "address"},
                        {"name": "tokenId", "type": "uint256"},
                        {"name": "makerAmount", "type": "uint256"},
                        {"name": "takerAmount", "type": "uint256"},
                        {"name": "expiration", "type": "uint256"},
                        {"name": "nonce", "type": "uint256"},
                        {"name": "feeRateBps", "type": "uint256"},
                        {"name": "side", "type": "uint8"},
                        {"name": "signatureType", "type": "uint8"},
                    ],
                },
                primary_type="Order",
                message_data=order,
            )
        )
        return "0x" + signed.signature.hex()

    def market_buy(
        self,
        token_id: str,
        amount_usd: float,
        max_price: float = 0.99,
    ) -> OrderResult:
        """
        Place a market buy order for outcome tokens.
        
        Args:
            token_id: Outcome token to buy (YES or NO)
            amount_usd: USD amount to spend
            max_price: Maximum price willing to pay (0 to 1)
        """
        print(f"📈 Market BUY: ${amount_usd:.2f} of token {token_id[:20]}... @ max {max_price:.2f}")
        
        # Convert to on-chain amounts (USDC has 6 decimals)
        usdc_amount = int(amount_usd * 1_000_000)
        token_amount = int(usdc_amount / max_price)
        
        salt = int(time.time() * 1000)
        expiration = int(time.time()) + 3600  # 1 hour
        nonce = 0
        
        order = {
            "salt": salt,
            "maker": self.address,
            "signer": self.address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id),
            "makerAmount": usdc_amount,
            "takerAmount": token_amount,
            "expiration": expiration,
            "nonce": nonce,
            "feeRateBps": 0,
            "side": 0,  # 0 = BUY
            "signatureType": 2,  # EIP-712
        }
        
        try:
            signature = self._sign_order(order)
        except Exception as e:
            return OrderResult(success=False, error=f"Sign failed: {e}")
        
        # Post to CLOB
        payload = {
            "order": {
                "salt": str(salt),
                "maker": self.address,
                "signer": self.address,
                "taker": "0x0000000000000000000000000000000000000000",
                "tokenId": token_id,
                "makerAmount": str(usdc_amount),
                "takerAmount": str(token_amount),
                "expiration": str(expiration),
                "nonce": str(nonce),
                "feeRateBps": "0",
                "side": "BUY",
                "signatureType": 2,
                "signature": signature,
            },
            "owner": self.funder,
            "orderType": "FOK",  # Fill or Kill for market orders
        }
        
        result = self._fetch(f"{CLOB_BASE}/order", method="POST", data=payload, auth=True)
        
        if "error" in result:
            return OrderResult(success=False, error=result["error"], details=result)
        
        order_id = result.get("orderID", result.get("id", ""))
        print(f"  ✅ Order placed: {order_id}")
        return OrderResult(success=True, order_id=order_id, details=result)

    def get_positions(self) -> list:
        """Get current open positions."""
        return self._fetch(f"{CLOB_BASE}/positions?owner={self.address}")

    def get_trades(self) -> list:
        """Get recent trades."""
        return self._fetch(f"{CLOB_BASE}/trades?maker_address={self.address}")


# === CLI ===
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
    
    clob = PolymarketCLOB()
    
    print(f"\n🐡 NemoFish CLOB Trader")
    print(f"  Address: {clob.address}")
    print(f"  API Key: {clob.api_key[:12]}...")
    
    # Test connection
    t = clob.get_server_time()
    print(f"  Server:  {t}")
    
    # Test with a small order if arg provided
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        token_id = sys.argv[2] if len(sys.argv) > 2 else ""
        amount = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
        if token_id:
            mid = clob.get_midpoint(token_id)
            print(f"\n  Midpoint: {mid:.4f}")
            result = clob.market_buy(token_id, amount, max_price=min(mid * 1.05, 0.99))
            print(f"  Result: {result}")
