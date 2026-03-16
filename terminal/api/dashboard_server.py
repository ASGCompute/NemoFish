"""
NemoFish Dashboard API Server
===============================
Lightweight HTTP server serving data to the React dashboard.
Uses api-tennis.com for LIVE scores/odds and RapidAPI for news.

Endpoints:
  GET /api/kpi          — Portfolio KPIs (bankroll, P&L, win rate)
  GET /api/signals      — Current bet signals from swarm
  GET /api/trades       — Trade journal
  GET /api/live         — REAL live/today matches from api-tennis.com
  GET /api/news         — Tennis news feed
  GET /api/odds         — Odds movements / market reaction
  GET /api/feed         — Full aggregated feed (all above)

Runs on port 8888 by default.
"""

import json
import sys
import os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from typing import Dict
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from feeds.rapidapi_tennis import TennisDataFeed
from feeds.api_tennis import ApiTennisClient
from feeds.sportradar_tennis import SportradarTennisClient
from execution.pnl_tracker import PnLTracker


class DashboardAPI(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard API."""

    # Shared state across requests
    feed = None
    tennis_api = None
    sportradar = None
    tracker = None
    _cached_live = None
    _cached_live_ts = None
    _cached_fixtures = None
    _cached_fixtures_ts = None
    _cached_rankings = None
    _cached_rankings_ts = None

    @classmethod
    def init_services(cls, api_key: str = None, bankroll: float = 10000):
        """Initialize shared services."""
        cls.feed = TennisDataFeed(api_key)
        cls.tennis_api = ApiTennisClient()
        cls.sportradar = SportradarTennisClient()
        cls.tracker = PnLTracker(initial_bankroll=bankroll)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        routes = {
            "/api/kpi": self._handle_kpi,
            "/api/signals": self._handle_signals,
            "/api/trades": self._handle_trades,
            "/api/live": self._handle_live,
            "/api/news": self._handle_news,
            "/api/odds": self._handle_odds,
            "/api/feed": self._handle_feed,
            "/api/rankings": self._handle_rankings,
            "/api/health": self._handle_health,
        }

        handler = routes.get(path)
        if handler:
            try:
                handler()
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json_response({"error": str(e)}, 500)
        else:
            self._json_response({"error": "Not found", "routes": list(routes.keys())}, 404)

    def _handle_health(self):
        self._json_response({
            "status": "ok",
            "service": "NemoFish Dashboard API",
            "timestamp": datetime.now().isoformat(),
            "data_source": "api-tennis.com",
        })

    def _handle_kpi(self):
        tracker = self.__class__.tracker
        total_pnl = tracker.total_pnl()
        bankroll = tracker.bankroll

        self._json_response({
            "bankroll": round(bankroll, 2),
            "initialBankroll": tracker.initial_bankroll,
            "totalPnl": round(total_pnl, 2),
            "dailyPnl": round(total_pnl, 2),
            "winRate": round(tracker.win_rate() * 100, 1),
            "totalBets": len(tracker.trades),
            "roi": round(tracker.roi() * 100, 1),
            "sharpe": round(tracker.sharpe_ratio(), 2),
            "maxDrawdown": round(tracker.max_drawdown() * 100, 1),
            "btcEquivalent": round(bankroll / 71754, 6),
            "activePositions": 0,
        })

    def _handle_signals(self):
        """Current bet signals (demo + TODO: live swarm)."""
        signals = [
            {
                "id": "NF-A3CC6A25", "match": "Djokovic vs Alcaraz",
                "playerA": "Novak Djokovic", "playerB": "Carlos Alcaraz",
                "pick": "Novak Djokovic", "odds": 2.40, "edge": 0.138,
                "betSize": 250, "confidence": "LOW", "action": "BET",
                "surface": "Hard", "round": "QF", "modelProb": 0.552,
                "agents": [
                    {"agentName": "StatBot", "role": "Statistical", "probA": 0.68, "confidence": 0.9},
                    {"agentName": "PsychBot", "role": "Psychology", "probA": 0.48, "confidence": 0.6},
                    {"agentName": "MarketBot", "role": "Market", "probA": 0.40, "confidence": 0.8},
                    {"agentName": "ContrarianBot", "role": "Contrarian", "probA": 0.50, "confidence": 0.5},
                    {"agentName": "NewsBot", "role": "News", "probA": 0.50, "confidence": 0.5},
                ],
            },
            {
                "id": "NF-3513D00B", "match": "Medvedev vs de Minaur",
                "playerA": "Daniil Medvedev", "playerB": "Alex de Minaur",
                "pick": "Daniil Medvedev", "odds": 1.80, "edge": 0.120,
                "betSize": 250, "confidence": "LOW", "action": "BET",
                "surface": "Hard", "round": "R16", "modelProb": 0.675,
                "agents": [
                    {"agentName": "StatBot", "role": "Statistical", "probA": 0.93, "confidence": 0.9},
                    {"agentName": "PsychBot", "role": "Psychology", "probA": 0.52, "confidence": 0.6},
                    {"agentName": "MarketBot", "role": "Market", "probA": 0.54, "confidence": 0.8},
                    {"agentName": "ContrarianBot", "role": "Contrarian", "probA": 0.49, "confidence": 0.5},
                    {"agentName": "NewsBot", "role": "News", "probA": 0.50, "confidence": 0.5},
                ],
            },
            {
                "id": "NF-36A012DD", "match": "Sinner vs Alcaraz",
                "playerA": "Jannik Sinner", "playerB": "Carlos Alcaraz",
                "pick": "Jannik Sinner", "odds": 1.55, "edge": 0.051,
                "betSize": 179.79, "confidence": "HIGH", "action": "BET",
                "surface": "Hard", "round": "F", "modelProb": 0.693,
                "agents": [
                    {"agentName": "StatBot", "role": "Statistical", "probA": 0.87, "confidence": 0.9},
                    {"agentName": "PsychBot", "role": "Psychology", "probA": 0.55, "confidence": 0.6},
                    {"agentName": "MarketBot", "role": "Market", "probA": 0.62, "confidence": 0.8},
                    {"agentName": "ContrarianBot", "role": "Contrarian", "probA": 0.50, "confidence": 0.5},
                    {"agentName": "NewsBot", "role": "News", "probA": 0.50, "confidence": 0.5},
                ],
            },
        ]
        self._json_response({"signals": signals})

    def _handle_trades(self):
        trades = [asdict(t) for t in self.__class__.tracker.trades]
        self._json_response({"trades": trades})

    def _handle_live(self):
        """
        LIVE matches from api-tennis.com (REAL DATA).
        Returns live + today's fixtures converted to dashboard format.
        Caches for 30 seconds to limit API calls.
        """
        cls = self.__class__
        now = datetime.now()

        # Cache livescore for 30 seconds
        if cls._cached_live is None or cls._cached_live_ts is None or \
           (now - cls._cached_live_ts).total_seconds() > 30:
            try:
                live_matches = cls.tennis_api.get_livescore()
                cls._cached_live = live_matches
                cls._cached_live_ts = now
            except Exception as e:
                print(f"⚠️  Livescore error: {e}")
                cls._cached_live = cls._cached_live or []

        # Cache fixtures for 5 minutes
        if cls._cached_fixtures is None or cls._cached_fixtures_ts is None or \
           (now - cls._cached_fixtures_ts).total_seconds() > 300:
            try:
                today = now.strftime("%Y-%m-%d")
                cls._cached_fixtures = cls.tennis_api.get_fixtures(
                    date_start=today, date_stop=today
                )
                cls._cached_fixtures_ts = now
            except Exception as e:
                print(f"⚠️  Fixtures error: {e}")
                cls._cached_fixtures = cls._cached_fixtures or []

        # Convert to dashboard format
        dashboard_matches = []

        # Live matches first
        for m in (cls._cached_live or []):
            score_str = ""
            if m.scores:
                score_str = " ".join(
                    f"{s.get('score_first', '0')}-{s.get('score_second', '0')}"
                    for s in m.scores
                )
            dashboard_matches.append({
                "event_key": m.event_key,
                "playerA": m.player_a,
                "playerB": m.player_b,
                "score": score_str or m.final_result,
                "game_score": m.game_result,
                "status": "live",
                "set_status": m.status,
                "serve": m.serve,
                "tournament": m.tournament,
                "round": m.round_name,
                "event_type": m.event_type,
                "time": m.time,
                "date": m.date,
                "oddsA": None,
                "oddsB": None,
            })

        # Today's fixtures (not live)
        live_keys = {m.event_key for m in (cls._cached_live or [])}
        for m in (cls._cached_fixtures or []):
            if m.event_key in live_keys:
                continue  # Skip if already in live

            # Filter to ATP/WTA singles for cleaner display
            etype = m.event_type.lower()
            if not any(t in etype for t in ["atp singles", "wta singles"]):
                continue

            status = "finished" if m.winner else "scheduled"
            score_str = ""
            if m.scores:
                score_str = " ".join(
                    f"{s.get('score_first', '0')}-{s.get('score_second', '0')}"
                    for s in m.scores
                )

            dashboard_matches.append({
                "event_key": m.event_key,
                "playerA": m.player_a,
                "playerB": m.player_b,
                "score": score_str or m.final_result,
                "game_score": m.game_result,
                "status": status,
                "set_status": m.status,
                "serve": None,
                "tournament": m.tournament,
                "round": m.round_name,
                "event_type": m.event_type,
                "time": m.time,
                "date": m.date,
                "oddsA": None,
                "oddsB": None,
            })

        live_count = len([m for m in dashboard_matches if m["status"] == "live"])
        total_count = len(dashboard_matches)

        self._json_response({
            "matches": dashboard_matches,
            "live_count": live_count,
            "total_count": total_count,
            "source": "api-tennis.com",
            "timestamp": now.isoformat(),
            "cached": cls._cached_live_ts.isoformat() if cls._cached_live_ts else None,
        })

    def _handle_news(self):
        """Tennis news from RapidAPI (demo fallback)."""
        news = self.__class__.feed.get_news()
        self._json_response({
            "news": [asdict(n) for n in news],
            "count": len(news),
        })

    def _handle_odds(self):
        """Odds movements from RapidAPI feed (demo fallback)."""
        movements = self.__class__.feed.get_odds_movements()
        self._json_response({
            "movements": [asdict(o) for o in movements],
        })

    def _handle_rankings(self):
        """ATP/WTA rankings from Sportradar (cached 1 hour)."""
        cls = self.__class__
        now = datetime.now()

        if cls._cached_rankings is None or cls._cached_rankings_ts is None or \
           (now - cls._cached_rankings_ts).total_seconds() > 3600:
            try:
                raw = cls.sportradar.get_rankings()
                cls._cached_rankings = {
                    tour: [asdict(r) for r in entries[:20]]
                    for tour, entries in raw.items()
                }
                cls._cached_rankings_ts = now
            except Exception as e:
                print(f"⚠️  Rankings error: {e}")
                cls._cached_rankings = cls._cached_rankings or {}

        self._json_response({
            "rankings": cls._cached_rankings,
            "source": "sportradar.com",
            "cached": cls._cached_rankings_ts.isoformat() if cls._cached_rankings_ts else None,
        })

    def _handle_feed(self):
        """Full aggregated feed."""
        full = self.__class__.feed.get_full_feed()

        tracker = self.__class__.tracker
        full["kpi"] = {
            "bankroll": round(tracker.bankroll, 2),
            "totalPnl": round(tracker.total_pnl(), 2),
            "winRate": round(tracker.win_rate() * 100, 1),
            "totalBets": len(tracker.trades),
            "roi": round(tracker.roi() * 100, 1),
            "btcEquivalent": round(tracker.bankroll / 71754, 6),
        }
        full["source"] = "api-tennis.com + RapidAPI"
        self._json_response(full)

    def log_message(self, format, *args):
        pass  # Suppress default logging


def run_server(port: int = 8888, api_key: str = None):
    """Start the dashboard API server."""
    DashboardAPI.init_services(api_key=api_key)

    server = HTTPServer(("0.0.0.0", port), DashboardAPI)
    print(f"{'='*60}")
    print(f"  🐡 NEMOFISH DASHBOARD API")
    print(f"  Running on http://localhost:{port}")
    print(f"  Data Sources:")
    print(f"    api-tennis.com   — Live scores, fixtures, odds")
    print(f"    sportradar.com   — Rankings, profiles, probabilities")
    print(f"    rapidapi.com     — News feed")
    print(f"  Endpoints:")
    print(f"    GET /api/health    — Health check")
    print(f"    GET /api/kpi       — Portfolio KPIs")
    print(f"    GET /api/signals   — Bet signals")
    print(f"    GET /api/trades    — Trade journal")
    print(f"    GET /api/live      — Live matches (api-tennis.com)")
    print(f"    GET /api/news      — Tennis news")
    print(f"    GET /api/odds      — Odds movements")
    print(f"    GET /api/rankings  — ATP/WTA rankings (sportradar)")
    print(f"    GET /api/feed      — Full feed")
    print(f"{'='*60}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    run_server(port=port, api_key=api_key)
