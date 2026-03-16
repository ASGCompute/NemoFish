"""
Polymarket API Client
======================
Interface to Polymarket CLOB API for:
- Market discovery (search tennis, hockey, crypto markets)
- Odds retrieval (prices = implied probabilities)
- Order placement (requires API credentials)
- Position tracking

Docs: https://docs.polymarket.com/
CLOB API: https://clob.polymarket.com

No API key needed for reading markets. 
Keys needed for trading (EIP-712 + HMAC-SHA256).
"""

import json
import urllib.request
import urllib.error
from typing import List, Optional, Dict
from dataclasses import dataclass
from datetime import datetime


CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


@dataclass
class PolymarketEvent:
    """A Polymarket event (e.g., 'Will Sinner win Miami Open 2026?')"""
    id: str
    title: str
    slug: str
    end_date: Optional[str]
    active: bool
    closed: bool
    markets: List["PolymarketMarket"]
    volume: float = 0.0
    liquidity: float = 0.0


@dataclass
class PolymarketMarket:
    """A single market within an event (Yes/No outcome)."""
    condition_id: str
    question: str
    outcome_yes_price: float  # 0.0 to 1.0 = implied probability
    outcome_no_price: float
    volume: float
    liquidity: float
    active: bool
    token_id_yes: str = ""
    token_id_no: str = ""


class PolymarketClient:
    """
    Client for Polymarket (read-only for now, trading requires credentials).
    
    Usage:
        pm = PolymarketClient()
        
        # Search for tennis markets
        events = pm.search_events("tennis")
        for e in events:
            print(f"{e.title} | Volume: ${e.volume:,.0f}")
            
        # Search for NHL markets
        events = pm.search_events("NHL")
        
        # Search for Bitcoin
        events = pm.search_events("Bitcoin price")
    """

    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key
        self.api_secret = api_secret

    def _fetch(self, url: str, params: Dict = None) -> dict:
        """Fetch JSON from API."""
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "NemoFish-Terminal/1.0")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            print(f"Polymarket API error {e.code}: {url}")
            return {}
        except Exception as e:
            print(f"Polymarket API request failed: {e}")
            return {}

    def search_events(
        self,
        query: str,
        limit: int = 100,
        active: bool = True,
        closed: bool = False,
    ) -> List[PolymarketEvent]:
        """
        Search Polymarket events by keyword/tag.
        Uses the Gamma API with tag_slug for sport-specific search.
        """
        params = {
            "limit": str(limit),
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }
        if query:
            params["tag_slug"] = query

        data = self._fetch(f"{GAMMA_BASE}/events", params)

        events = []
        if isinstance(data, list):
            items = data
        else:
            items = data.get("data", data.get("events", []))

        for item in items:
            markets = []
            for m in item.get("markets", []):
                outcomes = m.get("outcomePrices", "[]")
                if isinstance(outcomes, str):
                    try:
                        prices = json.loads(outcomes)
                    except:
                        prices = [0.5, 0.5]
                else:
                    prices = outcomes

                yes_price = float(prices[0]) if len(prices) > 0 else 0.5
                no_price = float(prices[1]) if len(prices) > 1 else 1 - yes_price

                tokens = m.get("clobTokenIds", "[]")
                if isinstance(tokens, str):
                    try:
                        token_ids = json.loads(tokens)
                    except:
                        token_ids = ["", ""]
                else:
                    token_ids = tokens

                markets.append(PolymarketMarket(
                    condition_id=m.get("conditionId", ""),
                    question=m.get("question", ""),
                    outcome_yes_price=yes_price,
                    outcome_no_price=no_price,
                    volume=float(m.get("volume", 0) or 0),
                    liquidity=float(m.get("liquidityNum", 0) or 0),
                    active=m.get("active", True),
                    token_id_yes=token_ids[0] if len(token_ids) > 0 else "",
                    token_id_no=token_ids[1] if len(token_ids) > 1 else "",
                ))

            events.append(PolymarketEvent(
                id=item.get("id", ""),
                title=item.get("title", ""),
                slug=item.get("slug", ""),
                end_date=item.get("endDate"),
                active=item.get("active", True),
                closed=item.get("closed", False),
                markets=markets,
                volume=float(item.get("volume", 0) or 0),
                liquidity=float(item.get("liquidityNum", 0) or 0),
            ))

        return sorted(events, key=lambda e: e.volume, reverse=True)

    def get_market_price(self, token_id: str) -> Optional[float]:
        """Get current price for a specific outcome token."""
        data = self._fetch(f"{CLOB_BASE}/price", {"token_id": token_id})
        return float(data.get("price", 0)) if data else None

    def get_markets_by_tag(self, tag: str) -> List[PolymarketEvent]:
        """Get markets filtered by tag (sports, crypto, politics, etc.)"""
        return self.search_events(query=tag)

    def find_tennis_markets(self) -> List[PolymarketEvent]:
        """Find all active tennis prediction markets using tag_slug."""
        events = self.search_events("tennis", limit=100)
        # Also try atp tag for additional coverage
        atp_events = self.search_events("atp", limit=100)
        seen = set(e.id for e in events)
        for e in atp_events:
            if e.id not in seen:
                events.append(e)
                seen.add(e.id)
        return sorted(events, key=lambda e: e.volume, reverse=True)

    def find_hockey_markets(self) -> List[PolymarketEvent]:
        """Find all active NHL/hockey prediction markets."""
        results = self.search_events("NHL")
        results.extend(self.search_events("hockey"))
        # Deduplicate by ID
        seen = set()
        unique = []
        for e in results:
            if e.id not in seen:
                seen.add(e.id)
                unique.append(e)
        return sorted(unique, key=lambda e: e.volume, reverse=True)

    def find_bitcoin_markets(self) -> List[PolymarketEvent]:
        """Find all active Bitcoin prediction markets."""
        return self.search_events("Bitcoin")

    def find_edge_opportunities(
        self,
        events: List[PolymarketEvent],
        model_probs: Dict[str, float],
        min_edge: float = 0.03,
    ) -> List[dict]:
        """
        Compare model probabilities vs Polymarket prices to find edges.
        
        Args:
            events: List of Polymarket events
            model_probs: Dict mapping question → our model probability
            min_edge: Minimum edge to flag (default 3%)
            
        Returns: List of edge opportunities
        """
        opportunities = []
        for event in events:
            for market in event.markets:
                q = market.question
                if q in model_probs:
                    model_p = model_probs[q]
                    market_p = market.outcome_yes_price
                    edge = model_p - market_p

                    if abs(edge) >= min_edge:
                        opportunities.append({
                            "event": event.title,
                            "question": q,
                            "model_prob": round(model_p, 4),
                            "market_prob": round(market_p, 4),
                            "edge": round(edge, 4),
                            "edge_pct": f"{edge*100:.1f}%",
                            "side": "YES" if edge > 0 else "NO",
                            "volume": market.volume,
                            "token_id": market.token_id_yes if edge > 0 else market.token_id_no,
                        })

        return sorted(opportunities, key=lambda x: abs(x["edge"]), reverse=True)


# --- CLI Usage ---
if __name__ == "__main__":
    pm = PolymarketClient()

    print("=== POLYMARKET: Tennis Markets ===")
    tennis = pm.find_tennis_markets()
    for event in tennis[:5]:
        print(f"\n📎 {event.title}")
        print(f"   Volume: ${event.volume:,.0f}")
        for m in event.markets[:3]:
            print(f"   → {m.question}: YES {m.outcome_yes_price:.0%} | NO {m.outcome_no_price:.0%}")

    print("\n=== POLYMARKET: NHL/Hockey Markets ===")
    hockey = pm.find_hockey_markets()
    for event in hockey[:5]:
        print(f"\n📎 {event.title}")
        print(f"   Volume: ${event.volume:,.0f}")
        for m in event.markets[:3]:
            print(f"   → {m.question}: YES {m.outcome_yes_price:.0%} | NO {m.outcome_no_price:.0%}")

    print("\n=== POLYMARKET: Bitcoin Markets ===")
    btc = pm.find_bitcoin_markets()
    for event in btc[:5]:
        print(f"\n📎 {event.title}")
        print(f"   Volume: ${event.volume:,.0f}")
        for m in event.markets[:3]:
            print(f"   → {m.question}: YES {m.outcome_yes_price:.0%} | NO {m.outcome_no_price:.0%}")
