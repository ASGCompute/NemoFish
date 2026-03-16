"""
Polymarket CLOB Live Trading Client
=====================================
Uses REST API directly (no SDK dependency) for:
- Market discovery (tennis/sports markets)
- Price checking (current YES/NO prices)
- Order placement via Relayer API key
- Position tracking and P&L

Requires:
  POLYMARKET_API_KEY — Relayer API key from polymarket.com/settings
  POLYMARKET_WALLET  — Associated wallet address

Docs: https://docs.polymarket.com/trading/quickstart
CLOB: https://clob.polymarket.com
"""

import json
import os
import time
import hmac
import hashlib
import urllib.request
import urllib.error
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


# === Configuration ===
CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# Load from .env
ENV_PATH = Path(__file__).parent.parent.parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("POLYMARKET_API_KEY", "")
WALLET = os.environ.get("POLYMARKET_WALLET", "")


@dataclass
class Market:
    """A Polymarket market for a specific outcome."""
    condition_id: str
    question: str
    yes_price: float       # 0.0–1.0 (implied probability)
    no_price: float
    volume: float
    liquidity: float
    active: bool
    token_yes: str
    token_no: str
    neg_risk: bool = False
    tick_size: str = "0.01"
    event_title: str = ""
    event_slug: str = ""
    end_date: str = ""


@dataclass
class OrderResult:
    """Result of an order placement."""
    success: bool
    order_id: str = ""
    status: str = ""
    error: str = ""
    raw: Dict = field(default_factory=dict)


@dataclass
class Position:
    """A position in a Polymarket market."""
    market: str
    side: str           # "YES" / "NO"
    size: float         # Number of shares
    avg_price: float    # Average entry price
    current_price: float
    unrealized_pnl: float
    token_id: str = ""


class PolymarketTrader:
    """
    Live Polymarket CLOB trader.
    
    Two modes:
    1. PAPER — simulates orders, tracks P&L locally
    2. LIVE  — sends orders to Polymarket via Relayer API
    
    Usage:
        trader = PolymarketTrader(mode="PAPER")
        
        # Find tennis markets
        markets = trader.find_tennis_markets()
        
        # Place a bet
        result = trader.place_bet(
            market=markets[0],
            side="YES",
            amount_usd=10.0,
        )
    """

    def __init__(self, mode: str = "PAPER", api_key: str = None, wallet: str = None):
        self.mode = mode.upper()  # "PAPER" or "LIVE"
        self.api_key = api_key or API_KEY
        self.wallet = wallet or WALLET
        self.positions: List[Dict] = []
        self.orders: List[Dict] = []
        self.paper_balance = 500.0  # USDC starting balance for paper
        self.paper_trades: List[Dict] = []
        
        # Journal file
        self.journal_path = Path(__file__).parent / "trade_journal_live.json"
        self._load_journal()

    def _load_journal(self):
        """Load existing trade journal."""
        if self.journal_path.exists():
            try:
                data = json.loads(self.journal_path.read_text())
                self.paper_trades = data.get("trades", [])
                self.paper_balance = data.get("balance", 500.0)
            except:
                pass

    def _save_journal(self):
        """Persist trade journal."""
        data = {
            "balance": self.paper_balance,
            "trades": self.paper_trades,
            "last_updated": datetime.now().isoformat(),
            "mode": self.mode,
        }
        self.journal_path.write_text(json.dumps(data, indent=2))

    # === Market Discovery ===
    
    def _fetch(self, url: str, headers: Dict = None) -> Any:
        """HTTP GET with optional headers."""
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "NemoFish-Terminal/2.0")
        req.add_header("Accept", "application/json")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            print(f"⚠️  Polymarket HTTP {e.code}: {url[:80]} — {body[:200]}")
            return None
        except Exception as e:
            print(f"⚠️  Polymarket request failed: {e}")
            return None

    def _post(self, url: str, body: Dict, headers: Dict = None) -> Any:
        """HTTP POST with JSON body."""
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "NemoFish-Terminal/2.0")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ""
            print(f"⚠️  Polymarket POST {e.code}: {body_text[:300]}")
            return {"error": body_text, "code": e.code}
        except Exception as e:
            print(f"⚠️  Polymarket POST failed: {e}")
            return {"error": str(e)}

    def search_markets(self, query: str = None, tag_slug: str = None, limit: int = 100) -> List[Market]:
        """Search Polymarket events via Gamma API using tag_slug for sport filtering."""
        params = f"limit={limit}&active=true&closed=false"
        if tag_slug:
            params += f"&tag_slug={tag_slug}"
        url = f"{GAMMA_BASE}/events?{params}"
        data = self._fetch(url)
        if not data:
            return []

        items = data if isinstance(data, list) else data.get("data", [])
        markets = []

        for item in items:
            title = item.get("title", "")
            slug = item.get("slug", "")
            
            # If query specified, filter by keyword in title/slug
            if query and query.lower() not in title.lower() and query.lower() not in slug.lower():
                continue

            for m in item.get("markets", []):
                prices = m.get("outcomePrices", "[]")
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except:
                        prices = [0.5, 0.5]

                tokens = m.get("clobTokenIds", "[]")
                if isinstance(tokens, str):
                    try:
                        tokens = json.loads(tokens)
                    except:
                        tokens = ["", ""]

                markets.append(Market(
                    condition_id=m.get("conditionId", ""),
                    question=m.get("question", ""),
                    yes_price=float(prices[0]) if prices else 0.5,
                    no_price=float(prices[1]) if len(prices) > 1 else 0.5,
                    volume=float(m.get("volume", 0) or 0),
                    liquidity=float(m.get("liquidityNum", 0) or 0),
                    active=m.get("active", True),
                    token_yes=tokens[0] if tokens else "",
                    token_no=tokens[1] if len(tokens) > 1 else "",
                    neg_risk=m.get("negRisk", False),
                    tick_size=m.get("minimumTickSize", "0.01") or "0.01",
                    event_title=title,
                    event_slug=slug,
                    end_date=item.get("endDate", ""),
                ))

        return sorted(markets, key=lambda m: m.volume, reverse=True)

    def find_tennis_markets(self) -> List[Market]:
        """Find all active tennis markets using tag_slug for proper sport filtering."""
        results = []
        # Use tag_slug for Gamma API sport filtering
        for tag in ["tennis", "atp"]:
            results.extend(self.search_markets(tag_slug=tag, limit=100))
        # Deduplicate by condition_id
        seen = set()
        unique = []
        for m in results:
            if m.condition_id and m.condition_id not in seen:
                seen.add(m.condition_id)
                unique.append(m)
        return sorted(unique, key=lambda m: m.volume, reverse=True)

    def find_sports_markets(self) -> List[Market]:
        """Find all active sports markets."""
        results = []
        for q in ["tennis", "NBA", "NHL", "UFC", "football", "soccer"]:
            results.extend(self.search_markets(q))
        seen = set()
        unique = []
        for m in results:
            if m.condition_id not in seen:
                seen.add(m.condition_id)
                unique.append(m)
        return unique

    def get_price(self, token_id: str) -> Optional[float]:
        """Get current price for a token."""
        data = self._fetch(f"{CLOB_BASE}/price?token_id={token_id}")
        return float(data.get("price", 0)) if data else None

    def get_orderbook(self, token_id: str) -> Dict:
        """Get orderbook (bids/asks) for a token."""
        data = self._fetch(f"{CLOB_BASE}/book?token_id={token_id}")
        return data or {}

    # === Trading ===

    def place_bet(
        self,
        market: Market,
        side: str,      # "YES" or "NO"
        amount_usd: float,
        price: float = None,  # None = use current market price
    ) -> OrderResult:
        """
        Place a bet on a market outcome.
        
        In PAPER mode: simulates the trade locally.
        In LIVE mode: sends order to Polymarket CLOB.
        """
        side = side.upper()
        token_id = market.token_yes if side == "YES" else market.token_no
        current_price = market.yes_price if side == "YES" else market.no_price
        
        if price is None:
            # Use current market price
            price = current_price

        # Calculate size (number of shares)
        if price <= 0 or price >= 1:
            return OrderResult(success=False, error=f"Invalid price: {price}")
        
        size = amount_usd / price  # shares = dollars / price_per_share

        if self.mode == "PAPER":
            return self._paper_trade(market, side, price, size, amount_usd)
        else:
            return self._live_trade(market, side, price, size, token_id)

    def _paper_trade(
        self, market: Market, side: str, price: float,
        size: float, amount_usd: float
    ) -> OrderResult:
        """Simulate a trade in paper mode."""
        if amount_usd > self.paper_balance:
            return OrderResult(
                success=False,
                error=f"Insufficient balance: ${self.paper_balance:.2f} < ${amount_usd:.2f}"
            )

        trade_id = f"NF-PAPER-{int(time.time())}"
        trade = {
            "id": trade_id,
            "timestamp": datetime.now().isoformat(),
            "market": market.question,
            "event": market.event_title,
            "side": side,
            "price": round(price, 4),
            "size": round(size, 2),
            "amount_usd": round(amount_usd, 2),
            "status": "FILLED",
            "mode": "PAPER",
            "resolved": False,
            "pnl": 0.0,
        }

        self.paper_balance -= amount_usd
        self.paper_trades.append(trade)
        self._save_journal()

        print(f"📝 PAPER TRADE: {side} {market.question}")
        print(f"   Price: {price:.4f} | Size: {size:.2f} shares | ${amount_usd:.2f}")
        print(f"   Balance: ${self.paper_balance:.2f}")

        return OrderResult(
            success=True,
            order_id=trade_id,
            status="FILLED (PAPER)",
        )

    def _live_trade(
        self, market: Market, side: str, price: float,
        size: float, token_id: str
    ) -> OrderResult:
        """Send a real order to Polymarket CLOB."""
        if not self.api_key:
            return OrderResult(
                success=False,
                error="No POLYMARKET_API_KEY configured"
            )

        # Round price to tick size
        tick = float(market.tick_size)
        price = round(round(price / tick) * tick, 4)

        order_body = {
            "tokenID": token_id,
            "price": str(price),
            "size": str(round(size, 2)),
            "side": "BUY",
            "type": "GTC",  # Good Till Cancel
        }

        # Auth headers for Relayer API
        timestamp = str(int(time.time()))
        headers = {
            "POLY_API_KEY": self.api_key,
            "POLY_TIMESTAMP": timestamp,
            "POLY_ADDRESS": self.wallet,
        }

        print(f"🔴 LIVE ORDER: {side} {market.question}")
        print(f"   Token: {token_id[:20]}...")
        print(f"   Price: {price} | Size: {size:.2f}")

        result = self._post(f"{CLOB_BASE}/order", order_body, headers)

        if result and not result.get("error"):
            order_id = result.get("orderID", result.get("id", ""))
            status = result.get("status", "SUBMITTED")
            
            # Log trade
            trade = {
                "id": order_id,
                "timestamp": datetime.now().isoformat(),
                "market": market.question,
                "event": market.event_title,
                "side": side,
                "price": price,
                "size": round(size, 2),
                "amount_usd": round(price * size, 2),
                "status": status,
                "mode": "LIVE",
                "resolved": False,
                "pnl": 0.0,
                "raw": result,
            }
            self.paper_trades.append(trade)
            self._save_journal()

            print(f"   ✅ Order {order_id}: {status}")
            return OrderResult(
                success=True, order_id=order_id,
                status=status, raw=result,
            )
        else:
            error = str(result.get("error", "Unknown error"))
            print(f"   ❌ Order failed: {error}")
            return OrderResult(
                success=False, error=error, raw=result or {},
            )

    # === Position Management ===

    def get_balance(self) -> Dict:
        """Get current balance info."""
        if self.mode == "PAPER":
            total_invested = sum(t["amount_usd"] for t in self.paper_trades 
                               if not t.get("resolved"))
            return {
                "mode": "PAPER",
                "balance": round(self.paper_balance, 2),
                "invested": round(total_invested, 2),
                "total_trades": len(self.paper_trades),
                "open_positions": sum(1 for t in self.paper_trades if not t.get("resolved")),
            }
        else:
            # Try to get balance from CLOB
            # (requires full L2 auth which needs HMAC signing)
            return {
                "mode": "LIVE",
                "api_key": self.api_key[:12] + "...",
                "wallet": self.wallet,
                "note": "Use Polymarket UI to check USDC balance",
            }

    def get_open_positions(self) -> List[Dict]:
        """Get all open (unresolved) positions."""
        return [t for t in self.paper_trades if not t.get("resolved")]

    def resolve_position(self, trade_id: str, won: bool) -> float:
        """
        Resolve a position manually.
        Returns P&L.
        """
        for trade in self.paper_trades:
            if trade["id"] == trade_id and not trade.get("resolved"):
                trade["resolved"] = True
                trade["won"] = won
                
                if won:
                    # Winner gets $1 per share
                    payout = trade["size"] * 1.0
                    pnl = payout - trade["amount_usd"]
                else:
                    pnl = -trade["amount_usd"]
                
                trade["pnl"] = round(pnl, 2)
                self.paper_balance += trade["amount_usd"] + pnl
                self._save_journal()
                
                print(f"{'✅ WON' if won else '❌ LOST'} {trade['market']}")
                print(f"   P&L: ${pnl:+.2f} | Balance: ${self.paper_balance:.2f}")
                return pnl
        
        return 0.0

    def summary(self) -> str:
        """Get a summary of all trading activity."""
        total_trades = len(self.paper_trades)
        resolved = [t for t in self.paper_trades if t.get("resolved")]
        won = [t for t in resolved if t.get("won")]
        
        total_pnl = sum(t.get("pnl", 0) for t in resolved)
        win_rate = len(won) / len(resolved) * 100 if resolved else 0
        
        return (
            f"📊 NemoFish Trading Summary ({self.mode})\n"
            f"   Balance:    ${self.paper_balance:.2f}\n"
            f"   Trades:     {total_trades} total, {len(resolved)} resolved\n"
            f"   Win Rate:   {win_rate:.1f}%\n"
            f"   Total P&L:  ${total_pnl:+.2f}\n"
            f"   Open:       {total_trades - len(resolved)} positions\n"
        )


# === CLI Demo ===
if __name__ == "__main__":
    trader = PolymarketTrader(mode="PAPER")
    
    print("=" * 60)
    print("  🐡 NEMOFISH — Polymarket Live Trader")
    print(f"  Mode: {trader.mode} | API: {'✅' if trader.api_key else '❌'}")
    print(f"  Wallet: {trader.wallet[:20]}..." if trader.wallet else "  Wallet: N/A")
    print("=" * 60)

    # Search for tennis markets
    print("\n🔎 Searching tennis markets...")
    tennis = trader.find_tennis_markets()
    
    if tennis:
        print(f"\n📎 Found {len(tennis)} tennis market(s):\n")
        for i, m in enumerate(tennis[:10]):
            edge_indicator = ""
            print(f"  {i+1}. {m.question}")
            print(f"     Event: {m.event_title}")
            print(f"     YES: {m.yes_price:.0%} | NO: {m.no_price:.0%}")
            print(f"     Vol: ${m.volume:,.0f} | Liq: ${m.liquidity:,.0f}")
            print()
    else:
        print("  No tennis markets found on Polymarket currently")
        
        # Try broader sports search
        print("\n🔎 Searching all sports markets...")
        sports = trader.find_sports_markets()
        if sports:
            print(f"\n📎 Found {len(sports)} sports market(s):\n")
            for i, m in enumerate(sports[:10]):
                print(f"  {i+1}. {m.question}")
                print(f"     YES: {m.yes_price:.0%} | NO: {m.no_price:.0%}")
                print(f"     Vol: ${m.volume:,.0f}")
                print()

    # Show balance
    print(f"\n{trader.summary()}")
