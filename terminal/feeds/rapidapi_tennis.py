"""
RapidAPI Tennis Data Feeds
===========================
Integration with RapidAPI tennis APIs for live data:

1. Ultimate Tennis — Live scores + live betting odds
2. AllScores — Match results, rankings, news
3. LiveScore — Sports news feed
4. Tennis News — Tennis-specific news

Free tiers:
  - Ultimate Tennis: 60 req/month
  - AllScores: 100 req/day
  - LiveScore: 500 req/month

Set RAPIDAPI_KEY in environment or .env file.
"""

import json
import os
import urllib.request
import urllib.error
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime


RAPIDAPI_HOST_TENNIS = "ultimate-tennis1.p.rapidapi.com"
RAPIDAPI_HOST_ALLSCORES = "allscores.p.rapidapi.com"
RAPIDAPI_HOST_LIVESCORE = "livescore6.p.rapidapi.com"

@dataclass
class LiveMatch:
    """A live tennis match."""
    match_id: str
    player_a: str
    player_b: str
    score: str
    status: str          # "live", "finished", "scheduled"
    tournament: str
    round_name: str
    surface: str
    start_time: str
    odds_a: Optional[float] = None
    odds_b: Optional[float] = None
    set_scores: List[str] = field(default_factory=list)
    server: str = ""     # Who is serving

@dataclass
class NewsItem:
    """A tennis news item."""
    title: str
    source: str
    url: str
    published: str
    category: str = ""   # injury, transfer, preview, result
    sentiment: str = ""  # positive, negative, neutral
    players: List[str] = field(default_factory=list)

@dataclass
class OddsMovement:
    """Odds movement for a match."""
    match_id: str
    player_a: str
    player_b: str
    odds_a_open: float
    odds_b_open: float
    odds_a_current: float
    odds_b_current: float
    movement_a: float    # Current - Open
    movement_b: float
    timestamp: str


class RapidAPIClient:
    """
    Base client for RapidAPI requests.
    Handles authentication and rate limiting.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("RAPIDAPI_KEY", "")
        self._request_count = 0

    def _fetch(self, host: str, path: str, params: Dict = None) -> dict:
        """Make authenticated request to RapidAPI."""
        url = f"https://{host}{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url = f"{url}?{query}"

        req = urllib.request.Request(url)
        req.add_header("x-rapidapi-key", self.api_key)
        req.add_header("x-rapidapi-host", host)
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                self._request_count += 1
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"⚠️  Rate limit hit on {host}")
            elif e.code == 403:
                print(f"⚠️  API key invalid or not subscribed to {host}")
            else:
                print(f"⚠️  API error {e.code}: {host}{path}")
            return {}
        except Exception as e:
            print(f"⚠️  Request failed: {e}")
            return {}


class UltimateTennisAPI(RapidAPIClient):
    """
    Ultimate Tennis API — Live scores + betting odds.
    Host: ultimate-tennis1.p.rapidapi.com
    Free: 60 req/month
    
    Key endpoints:
      /live/scores     — Live match scores with betting odds
      /live/stats      — Live match statistics
      /rankings/atp    — ATP rankings
      /rankings/wta    — WTA rankings
    """

    HOST = RAPIDAPI_HOST_TENNIS

    def get_live_scores(self) -> List[LiveMatch]:
        """Get all live tennis matches with scores and odds."""
        data = self._fetch(self.HOST, "/live/scores")
        matches = []
        
        if not data:
            return self._get_demo_live_matches()

        items = data if isinstance(data, list) else data.get("matches", data.get("data", []))
        for m in items:
            try:
                match = LiveMatch(
                    match_id=str(m.get("id", "")),
                    player_a=m.get("player1", m.get("home", {}).get("name", "Player A")),
                    player_b=m.get("player2", m.get("away", {}).get("name", "Player B")),
                    score=m.get("score", ""),
                    status=m.get("status", "live"),
                    tournament=m.get("tournament", m.get("competitionName", "")),
                    round_name=m.get("round", ""),
                    surface=m.get("surface", "Hard"),
                    start_time=m.get("startTime", m.get("date", "")),
                    odds_a=m.get("odds", {}).get("home") if isinstance(m.get("odds"), dict) else None,
                    odds_b=m.get("odds", {}).get("away") if isinstance(m.get("odds"), dict) else None,
                )
                matches.append(match)
            except Exception:
                continue

        return matches or self._get_demo_live_matches()

    def get_atp_rankings(self, limit: int = 50) -> List[Dict]:
        """Get current ATP rankings."""
        data = self._fetch(self.HOST, "/rankings/atp", {"limit": str(limit)})
        if not data:
            return self._get_demo_rankings()
        return data if isinstance(data, list) else data.get("rankings", [])

    def _get_demo_live_matches(self) -> List[LiveMatch]:
        """Demo data for development without API key."""
        return [
            LiveMatch(
                match_id="demo-1", player_a="Jannik Sinner", player_b="Ben Shelton",
                score="6-4 3-2", status="live", tournament="Miami Open 2026",
                round_name="R32", surface="Hard", start_time="2026-03-17 15:00",
                odds_a=1.18, odds_b=5.50, set_scores=["6-4", "3-2"], server="Sinner"
            ),
            LiveMatch(
                match_id="demo-2", player_a="Carlos Alcaraz", player_b="Hubert Hurkacz",
                score="4-6 6-3 2-1", status="live", tournament="Miami Open 2026",
                round_name="R32", surface="Hard", start_time="2026-03-17 17:00",
                odds_a=1.35, odds_b=3.40, set_scores=["4-6", "6-3", "2-1"], server="Alcaraz"
            ),
            LiveMatch(
                match_id="demo-3", player_a="Alexander Zverev", player_b="Lorenzo Musetti",
                score="7-5 6-4", status="finished", tournament="Miami Open 2026",
                round_name="R32", surface="Hard", start_time="2026-03-17 12:00",
                odds_a=1.28, odds_b=4.00, set_scores=["7-5", "6-4"],
            ),
            LiveMatch(
                match_id="demo-4", player_a="Daniil Medvedev", player_b="Tommy Paul",
                score="", status="scheduled", tournament="Miami Open 2026",
                round_name="R16", surface="Hard", start_time="2026-03-18 14:00",
                odds_a=1.65, odds_b=2.30,
            ),
            LiveMatch(
                match_id="demo-5", player_a="Novak Djokovic", player_b="Frances Tiafoe",
                score="6-3 5-4", status="live", tournament="Miami Open 2026",
                round_name="R32", surface="Hard", start_time="2026-03-17 19:00",
                odds_a=1.12, odds_b=7.00, set_scores=["6-3", "5-4"], server="Djokovic"
            ),
        ]

    def _get_demo_rankings(self) -> List[Dict]:
        return [
            {"rank": 1, "name": "Jannik Sinner", "points": 11830, "country": "ITA"},
            {"rank": 2, "name": "Alexander Zverev", "points": 8135, "country": "GER"},
            {"rank": 3, "name": "Carlos Alcaraz", "points": 7010, "country": "ESP"},
            {"rank": 4, "name": "Taylor Fritz", "points": 5050, "country": "USA"},
            {"rank": 5, "name": "Daniil Medvedev", "points": 4800, "country": "RUS"},
        ]


class AllScoresAPI(RapidAPIClient):
    """
    AllScores API — Matches, rankings, news.
    Host: allscores.p.rapidapi.com
    Free: 100 req/day
    """

    HOST = RAPIDAPI_HOST_ALLSCORES

    def get_tennis_news(self) -> List[NewsItem]:
        """Get latest tennis news."""
        data = self._fetch(self.HOST, "/api/allscores/news", {"sport": "tennis"})
        news = []

        if not data:
            return self._get_demo_news()

        items = data if isinstance(data, list) else data.get("news", data.get("data", []))
        for item in items[:20]:
            try:
                news.append(NewsItem(
                    title=item.get("title", ""),
                    source=item.get("source", "AllScores"),
                    url=item.get("url", ""),
                    published=item.get("publishedAt", item.get("date", "")),
                    category=item.get("category", "news"),
                ))
            except Exception:
                continue

        return news or self._get_demo_news()

    def _get_demo_news(self) -> List[NewsItem]:
        """Demo news for development."""
        return [
            NewsItem(
                title="Sinner enters Miami Open as top seed, targeting back-to-back titles",
                source="ATP Tour", url="https://atptour.com", published="2026-03-16T10:00:00Z",
                category="preview", sentiment="positive", players=["Jannik Sinner"]
            ),
            NewsItem(
                title="Djokovic hints at reduced schedule, Miami appearance uncertain until last minute",
                source="Tennis365", url="https://tennis365.com", published="2026-03-16T08:00:00Z",
                category="injury", sentiment="negative", players=["Novak Djokovic"]
            ),
            NewsItem(
                title="Alcaraz adjusting to new racquet setup ahead of hard court swing",
                source="ESPN Tennis", url="https://espn.com", published="2026-03-15T22:00:00Z",
                category="preview", sentiment="neutral", players=["Carlos Alcaraz"]
            ),
            NewsItem(
                title="Medvedev: 'Hard courts are my territory, I'm ready to fight'",
                source="Reuters", url="https://reuters.com", published="2026-03-15T18:00:00Z",
                category="preview", sentiment="positive", players=["Daniil Medvedev"]
            ),
            NewsItem(
                title="Fritz withdraws from doubles to focus on singles campaign",
                source="Tennis Channel", url="https://tennischannel.com", published="2026-03-15T15:00:00Z",
                category="news", sentiment="neutral", players=["Taylor Fritz"]
            ),
            NewsItem(
                title="Zverev vs Rune rivalry heats up: 'He knows I have his number'",
                source="Sky Sports", url="https://skysports.com", published="2026-03-15T12:00:00Z",
                category="preview", sentiment="neutral", players=["Alexander Zverev", "Holger Rune"]
            ),
            NewsItem(
                title="BREAKING: De Minaur nursing wrist discomfort, training limited",
                source="Tennis Australia", url="https://tennis.com.au", published="2026-03-15T09:00:00Z",
                category="injury", sentiment="negative", players=["Alex de Minaur"]
            ),
        ]


class LiveScoreAPI(RapidAPIClient):
    """
    LiveScore API — General sports news and scores.
    Host: livescore6.p.rapidapi.com
    Free: 500 req/month
    """

    HOST = RAPIDAPI_HOST_LIVESCORE

    def get_news(self, sport: str = "tennis") -> List[NewsItem]:
        """Get sports news."""
        data = self._fetch(self.HOST, "/news/v2/list", {"category": sport})
        news = []

        if not data:
            return []

        items = data.get("data", data.get("news", []))
        for item in items[:15]:
            try:
                news.append(NewsItem(
                    title=item.get("title", ""),
                    source="LiveScore",
                    url=item.get("url", ""),
                    published=item.get("publishedAt", ""),
                ))
            except Exception:
                continue

        return news


# === Aggregated Feed ===
class TennisDataFeed:
    """
    Aggregated feed combining all API sources.
    Provides a unified interface for the dashboard.
    
    Usage:
        feed = TennisDataFeed(api_key="your-rapidapi-key")
        live = feed.get_live_matches()
        news = feed.get_news()
        odds = feed.get_odds_movements()
    """

    def __init__(self, api_key: str = None):
        self.tennis = UltimateTennisAPI(api_key)
        self.allscores = AllScoresAPI(api_key)
        self.livescore = LiveScoreAPI(api_key)

    def get_live_matches(self) -> List[LiveMatch]:
        """Get all live tennis matches from best source."""
        return self.tennis.get_live_scores()

    def get_news(self) -> List[NewsItem]:
        """Get aggregated tennis news from all sources."""
        news = self.allscores.get_tennis_news()
        # Could add livescore news too, but save API calls
        return sorted(news, key=lambda n: n.published, reverse=True)

    def get_odds_movements(self) -> List[OddsMovement]:
        """Calculate odds movements from live matches."""
        matches = self.get_live_matches()
        movements = []

        for m in matches:
            if m.odds_a and m.odds_b:
                # Simulate opening odds (would come from historical data in production)
                open_a = m.odds_a * 0.95  # Approximate opening line
                open_b = m.odds_b * 1.05

                movements.append(OddsMovement(
                    match_id=m.match_id,
                    player_a=m.player_a,
                    player_b=m.player_b,
                    odds_a_open=round(open_a, 2),
                    odds_b_open=round(open_b, 2),
                    odds_a_current=m.odds_a,
                    odds_b_current=m.odds_b,
                    movement_a=round(m.odds_a - open_a, 3),
                    movement_b=round(m.odds_b - open_b, 3),
                    timestamp=datetime.now().isoformat(),
                ))

        return movements

    def get_full_feed(self) -> Dict:
        """Get everything in a single call — for the dashboard API."""
        live = self.get_live_matches()
        news = self.get_news()
        odds = self.get_odds_movements()

        return {
            "timestamp": datetime.now().isoformat(),
            "live_matches": [asdict(m) for m in live],
            "news": [asdict(n) for n in news],
            "odds_movements": [asdict(o) for o in odds],
            "stats": {
                "live_count": len([m for m in live if m.status == "live"]),
                "scheduled_count": len([m for m in live if m.status == "scheduled"]),
                "finished_count": len([m for m in live if m.status == "finished"]),
                "news_count": len(news),
                "api_requests_used": self.tennis._request_count + self.allscores._request_count,
            }
        }


# === CLI Demo ===
if __name__ == "__main__":
    feed = TennisDataFeed()

    print("=" * 60)
    print("  🎾 TENNIS DATA FEED — Live Demo")
    print("=" * 60)

    # Live matches
    matches = feed.get_live_matches()
    print(f"\n  🔴 LIVE MATCHES ({len([m for m in matches if m.status == 'live'])} active)")
    print("  " + "-" * 50)
    for m in matches:
        status_icon = {"live": "🔴", "finished": "✅", "scheduled": "📅"}.get(m.status, "❓")
        odds_str = f" | {m.odds_a:.2f} vs {m.odds_b:.2f}" if m.odds_a else ""
        print(f"  {status_icon} {m.player_a} vs {m.player_b}")
        print(f"     {m.tournament} {m.round_name} | {m.score or 'Not started'}{odds_str}")

    # News
    news = feed.get_news()
    print(f"\n  📰 NEWS ({len(news)} items)")
    print("  " + "-" * 50)
    for n in news[:5]:
        icon = {"injury": "🏥", "preview": "📋", "news": "📰", "result": "🏆"}.get(n.category, "📰")
        print(f"  {icon} {n.title}")
        print(f"     {n.source} | {n.published[:10]}")

    # Odds movements
    movements = feed.get_odds_movements()
    print(f"\n  📊 ODDS MOVEMENTS ({len(movements)} tracked)")
    print("  " + "-" * 50)
    for o in movements:
        dir_a = "↓" if o.movement_a < 0 else "↑"
        print(f"  {o.player_a} {o.odds_a_current:.2f} ({dir_a}{abs(o.movement_a):.3f}) vs "
              f"{o.player_b} {o.odds_b_current:.2f}")
