"""
The Odds API — Tennis Odds Client
===================================
Fetches real-time tennis match odds from The Odds API.

Free tier: 500 requests/month (enough for ~16/day).
Docs: https://the-odds-api.com/liveapi/guides/v4/

Usage:
    client = OddsAPIClient(api_key="YOUR_KEY")
    odds = client.get_tennis_odds()
    for match in odds:
        print(f"{match['home']} vs {match['away']}")
        for bm in match['bookmakers']:
            print(f"  {bm['name']}: {bm['odds_home']:.2f} / {bm['odds_away']:.2f}")
"""

import os
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass


# Tennis sport keys in The Odds API
TENNIS_SPORTS = [
    'tennis_atp_aus_open',
    'tennis_atp_french_open', 
    'tennis_atp_us_open',
    'tennis_atp_wimbledon',
    'tennis_atp_canadian_open',
    'tennis_atp_china_open',
    'tennis_atp_indian_wells',
    'tennis_atp_miami_open',
    'tennis_atp_monte_carlo',
    'tennis_atp_rome',
    'tennis_atp_madrid_open',
    'tennis_atp_shanghai',
    'tennis_atp_cincinnati_open',
    'tennis_atp_doha',
    'tennis_atp_dubai',
    'tennis_atp_halle',
    'tennis_atp_queens_club',
    'tennis_atp_vienna_open',
    'tennis_atp_paris_masters',
    'tennis_atp_adelaide',
    'tennis_atp_brisbane',
    'tennis_atp_united_cup',
]

BASE_URL = "https://api.the-odds-api.com/v4"


@dataclass
class MatchOdds:
    """Odds for a single tennis match from The Odds API."""
    match_id: str
    sport: str
    commence_time: str          # ISO format
    home_player: str
    away_player: str
    bookmakers: List[Dict]      # [{name, odds_home, odds_away}]
    best_odds_home: float       # Best available odds for home
    best_odds_away: float       # Best available odds for away
    avg_odds_home: float        # Average across bookmakers
    avg_odds_away: float
    implied_prob_home: float    # From average odds
    implied_prob_away: float


class OddsAPIClient:
    """
    Client for The Odds API — real-time tennis odds.
    
    Setup:
        1. Sign up at https://the-odds-api.com/
        2. Get free API key (500 requests/month)
        3. Set env var: export ODDS_API_KEY=your_key_here
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY", "")
        self.session = requests.Session()
        self._remaining_requests = None
        self._used_requests = None
        
        if not self.api_key:
            print("⚠️  ODDS_API_KEY not set. Get a free key at https://the-odds-api.com/")

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make authenticated GET request."""
        if not self.api_key:
            return None

        url = f"{BASE_URL}/{endpoint}"
        params = params or {}
        params['apiKey'] = self.api_key

        try:
            resp = self.session.get(url, params=params, timeout=15)
            
            # Track API usage from headers
            self._remaining_requests = resp.headers.get('x-requests-remaining')
            self._used_requests = resp.headers.get('x-requests-used')
            
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"⚠️  Odds API error: {e}")
            return None

    def get_available_sports(self) -> List[Dict]:
        """List all available sports (to find active tennis tournaments)."""
        data = self._get("sports")
        if not data:
            return []
        return [s for s in data if 'tennis' in s.get('key', '')]

    def get_tennis_odds(
        self,
        sport_key: str = None,
        regions: str = "us,eu,uk",
        markets: str = "h2h",
        odds_format: str = "decimal",
    ) -> List[MatchOdds]:
        """
        Fetch current tennis match odds.
        
        If no sport_key specified, tries all known tennis sports.
        Each call costs 1 API credit.
        
        Args:
            sport_key: Specific tournament key (e.g., 'tennis_atp_miami_open')
            regions: Bookmaker regions (us, eu, uk, au)
            markets: Market types (h2h = match winner)
            odds_format: decimal or american
            
        Returns:
            List of MatchOdds with odds from all bookmakers.
        """
        all_odds = []
        
        # If specific sport, just fetch that
        if sport_key:
            sports_to_check = [sport_key]
        else:
            # Check which tennis sports are currently active (1 credit)
            active = self.get_available_sports()
            sports_to_check = [s['key'] for s in active if not s.get('has_outrights')]
            if not sports_to_check:
                print("   ⚠️  No active tennis tournaments found")
                return []
            print(f"   📡 Active tennis tournaments: {len(sports_to_check)}")

        # Fetch odds for each active sport
        for sport in sports_to_check:
            data = self._get(f"sports/{sport}/odds", {
                'regions': regions,
                'markets': markets,
                'oddsFormat': odds_format,
            })
            
            if not data:
                continue
                
            for event in data:
                match_odds = self._parse_event(event, sport)
                if match_odds:
                    all_odds.append(match_odds)

        return all_odds

    def get_match_odds(self, home: str, away: str) -> Optional[MatchOdds]:
        """
        Find odds for a specific match by player names.
        Uses fuzzy matching on player names.
        """
        all_odds = self.get_tennis_odds()
        
        home_lower = home.lower()
        away_lower = away.lower()
        
        for odds in all_odds:
            h = odds.home_player.lower()
            a = odds.away_player.lower()
            
            # Check both orderings
            if (home_lower in h or h in home_lower) and \
               (away_lower in a or a in away_lower):
                return odds
            if (home_lower in a or a in home_lower) and \
               (away_lower in h or h in away_lower):
                # Swap home/away odds
                return MatchOdds(
                    match_id=odds.match_id,
                    sport=odds.sport,
                    commence_time=odds.commence_time,
                    home_player=home,
                    away_player=away,
                    bookmakers=[{
                        'name': bm['name'],
                        'odds_home': bm['odds_away'],
                        'odds_away': bm['odds_home'],
                    } for bm in odds.bookmakers],
                    best_odds_home=odds.best_odds_away,
                    best_odds_away=odds.best_odds_home,
                    avg_odds_home=odds.avg_odds_away,
                    avg_odds_away=odds.avg_odds_home,
                    implied_prob_home=odds.implied_prob_away,
                    implied_prob_away=odds.implied_prob_home,
                )
        
        return None

    def _parse_event(self, event: dict, sport: str) -> Optional[MatchOdds]:
        """Parse a single event from The Odds API response."""
        bookmakers_data = []
        all_home_odds = []
        all_away_odds = []
        
        home = event.get('home_team', '')
        away = event.get('away_team', '')
        
        if not home or not away:
            return None

        for bm in event.get('bookmakers', []):
            for market in bm.get('markets', []):
                if market.get('key') != 'h2h':
                    continue
                outcomes = {o['name']: o['price'] for o in market.get('outcomes', [])}
                
                odds_home = outcomes.get(home, 0)
                odds_away = outcomes.get(away, 0)
                
                if odds_home > 0 and odds_away > 0:
                    bookmakers_data.append({
                        'name': bm.get('title', bm.get('key', '')),
                        'odds_home': odds_home,
                        'odds_away': odds_away,
                    })
                    all_home_odds.append(odds_home)
                    all_away_odds.append(odds_away)

        if not bookmakers_data:
            return None

        avg_home = sum(all_home_odds) / len(all_home_odds)
        avg_away = sum(all_away_odds) / len(all_away_odds)

        return MatchOdds(
            match_id=event.get('id', ''),
            sport=sport,
            commence_time=event.get('commence_time', ''),
            home_player=home,
            away_player=away,
            bookmakers=bookmakers_data,
            best_odds_home=max(all_home_odds),
            best_odds_away=max(all_away_odds),
            avg_odds_home=round(avg_home, 3),
            avg_odds_away=round(avg_away, 3),
            implied_prob_home=round(1.0 / avg_home, 4) if avg_home > 0 else 0.5,
            implied_prob_away=round(1.0 / avg_away, 4) if avg_away > 0 else 0.5,
        )

    @property
    def usage(self) -> str:
        """Return API usage info."""
        if self._remaining_requests is not None:
            return f"Used: {self._used_requests}, Remaining: {self._remaining_requests}"
        return "No requests made yet"

    def save_odds_snapshot(self, odds: List[MatchOdds], path: str = None):
        """Save current odds to JSON for record-keeping."""
        if path is None:
            path = str(Path(__file__).parent.parent / "data" / "odds_snapshots" 
                       / f"odds_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
        
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'usage': self.usage,
            'matches': [
                {
                    'home': o.home_player,
                    'away': o.away_player,
                    'sport': o.sport,
                    'time': o.commence_time,
                    'avg_odds': [o.avg_odds_home, o.avg_odds_away],
                    'best_odds': [o.best_odds_home, o.best_odds_away],
                    'implied_prob': [o.implied_prob_home, o.implied_prob_away],
                    'bookmakers': o.bookmakers,
                }
                for o in odds
            ],
        }
        
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2)
        print(f"💾 Odds snapshot saved: {path}")


# === CLI Demo ===
if __name__ == "__main__":
    client = OddsAPIClient()
    
    if not client.api_key:
        print("\n⚠️  Set ODDS_API_KEY to use this module.")
        print("   Sign up free: https://the-odds-api.com/")
        print("\n   Example: export ODDS_API_KEY=abc123def456")
        print("\n   Demo mode — showing available tennis sports:")
        # Show available sports without needing key
    else:
        print("🎾 Fetching live tennis odds...")
        odds = client.get_tennis_odds()
        
        if odds:
            print(f"\n📊 Found {len(odds)} matches with odds:\n")
            for o in odds:
                print(f"  {o.home_player} vs {o.away_player}")
                print(f"    Time: {o.commence_time}")
                print(f"    Avg odds:  {o.avg_odds_home:.2f} / {o.avg_odds_away:.2f}")
                print(f"    Best odds: {o.best_odds_home:.2f} / {o.best_odds_away:.2f}")
                print(f"    Implied:   {o.implied_prob_home:.1%} / {o.implied_prob_away:.1%}")
                print(f"    Bookmakers: {len(o.bookmakers)}")
                for bm in o.bookmakers[:3]:
                    print(f"      {bm['name']}: {bm['odds_home']:.2f} / {bm['odds_away']:.2f}")
                print()
            
            # Save snapshot
            client.save_odds_snapshot(odds)
        else:
            print("   No tennis matches with odds found currently")
        
        print(f"\n📈 API Usage: {client.usage}")
