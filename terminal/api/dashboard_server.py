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
            "/api/strategies": self._handle_strategies,
            "/api/unresolved": self._handle_unresolved,
            "/api/slate": self._handle_slate,
            "/api/slate/status": self._handle_slate_status,
        }

        handler = routes.get(path)
        if handler:
            try:
                handler()
            except BrokenPipeError:
                pass  # Browser disconnected, ignore
            except Exception as e:
                try:
                    self._json_response({"error": str(e)}, 500)
                except BrokenPipeError:
                    pass
        else:
            # Check for parameterized match routes: /api/match/:id/:section
            if path.startswith("/api/match/"):
                parts = path.split("/")  # ['', 'api', 'match', id, section]
                if len(parts) >= 5:
                    match_id = parts[3]
                    section = parts[4]
                    try:
                        self._handle_match_section(match_id, section)
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        self._json_response({"error": str(e)}, 500)
                elif len(parts) == 4 and parts[3] == "list":
                    self._handle_match_list()
                else:
                    self._json_response({"error": "Missing section", "usage": "/api/match/:id/:section"}, 400)
            else:
                self._json_response({"error": "Not found", "routes": list(routes.keys())}, 404)

    def _handle_health(self):
        """Health check with source availability status."""
        env_keys = {
            "API_TENNIS_KEY": bool(os.environ.get("API_TENNIS_KEY")),
            "SPORTRADAR_API_KEY": bool(os.environ.get("SPORTRADAR_API_KEY")),
            "ODDS_API_KEY": bool(os.environ.get("ODDS_API_KEY")),
            "POLYMARKET_API_KEY": bool(os.environ.get("POLYMARKET_API_KEY")),
            "LLM_API_KEY": bool(os.environ.get("LLM_API_KEY")),
        }
        sackmann_path = Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp"
        sackmann_ok = sackmann_path.exists() and any(sackmann_path.glob("atp_matches_*.csv"))
        last_run = Path(__file__).parent.parent / "execution" / "last_run.json"
        last_run_ts = ""
        if last_run.exists():
            try:
                last_run_ts = json.loads(last_run.read_text()).get("timestamp", "")
            except Exception:
                pass

        self._json_response({
            "status": "ok",
            "service": "NemoFish Dashboard API",
            "timestamp": datetime.now().isoformat(),
            "data_source": "api-tennis.com",
            "env_keys": env_keys,
            "sackmann_data": sackmann_ok,
            "last_run": last_run_ts,
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
        """Current bet signals — from live swarm or SOURCE_UNAVAILABLE."""
        # TODO: wire up live swarm signals from last_run.json
        last_run_path = Path(__file__).parent.parent / "execution" / "last_run.json"
        if last_run_path.exists():
            try:
                data = json.loads(last_run_path.read_text())
                results = data.get("results", [])
                signals = []
                for r in results:
                    signals.append({
                        "id": r.get("order_id", "N/A"),
                        "match": r.get("match", ""),
                        "pick": r.get("pick", ""),
                        "odds": 0,
                        "edge": r.get("edge", 0),
                        "betSize": r.get("bet_size", 0),
                        "confidence": r.get("confidence", ""),
                        "action": "BET",
                        "modelProb": r.get("prob", 0),
                    })
                self._json_response({
                    "signals": signals,
                    "source": "live_runner",
                    "last_run": data.get("timestamp", ""),
                })
                return
            except Exception:
                pass

        self._json_response({
            "signals": [],
            "source": "SOURCE_UNAVAILABLE",
            "message": "Run live_runner.py to generate live signals",
        })

    def _handle_trades(self):
        trades = [asdict(t) for t in self.__class__.tracker.trades]
        self._json_response({"trades": trades})

    def _handle_strategies(self):
        """Strategy backtest results from run artifacts."""
        runs_dir = Path(__file__).parent.parent / "execution" / "runs"
        strategies = []

        if runs_dir.exists():
            # Find latest backtest results from any run
            for run_dir in sorted(runs_dir.iterdir(), reverse=True):
                backtest_file = run_dir / "backtest_results.json"
                if backtest_file.exists():
                    try:
                        data = json.loads(backtest_file.read_text())
                        if isinstance(data, list):
                            strategies = data
                        elif isinstance(data, dict) and "strategies" in data:
                            strategies = data["strategies"]
                        break  # Use latest only
                    except Exception:
                        continue

        # Also check root-level backtest output
        if not strategies:
            root_backtest = Path(__file__).parent.parent / "backtest_results.json"
            if root_backtest.exists():
                try:
                    data = json.loads(root_backtest.read_text())
                    if isinstance(data, list):
                        strategies = data
                    elif isinstance(data, dict) and "strategies" in data:
                        strategies = data["strategies"]
                except Exception:
                    pass

        self._json_response({
            "strategies": strategies,
            "source": "backtest_artifacts" if strategies else "none",
        })

    def _handle_unresolved(self):
        """UNRESOLVED_PLAYER entries from the latest run."""
        unresolved = []
        runs_dir = Path(__file__).parent.parent / "execution" / "runs"

        if runs_dir.exists():
            for run_dir in sorted(runs_dir.iterdir(), reverse=True):
                risk_file = run_dir / "risk_decisions.json"
                if risk_file.exists():
                    try:
                        data = json.loads(risk_file.read_text())
                        unresolved = [
                            d for d in data
                            if d.get("reason", "").startswith("UNRESOLVED_PLAYER")
                        ]
                        break
                    except Exception:
                        continue

        self._json_response({
            "unresolved": unresolved,
            "count": len(unresolved),
        })

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

    def _find_match_artifacts(self, match_id: str) -> Dict:
        """Find scenario artifacts by match slug or ID. Searches slate dirs first."""
        scenarios_dir = Path(__file__).parent.parent / "output" / "scenarios"
        if not scenarios_dir.exists():
            return {}

        artifacts = {}

        # 1. Search latest slate dirs first (newest first)
        for slate_dir in sorted(scenarios_dir.glob("slate_*"), reverse=True):
            if not slate_dir.is_dir():
                continue
            for f in slate_dir.glob("*.json"):
                name = f.stem
                if match_id in name or match_id.replace("-", "_") in name:
                    for suffix in ["dossier", "signals", "overlay", "report"]:
                        if name.endswith(f"_{suffix}") and suffix not in artifacts:
                            artifacts[suffix] = json.loads(f.read_text())
            if artifacts:
                return artifacts  # Found in slate, no need to search further

        # 2. Fallback: search loose files in scenarios_dir
        for f in sorted(scenarios_dir.glob("*.json"), reverse=True):
            name = f.stem
            if match_id in name or match_id.replace("-", "_") in name:
                for suffix in ["dossier", "signals", "overlay", "report"]:
                    if name.endswith(f"_{suffix}"):
                        artifacts[suffix] = json.loads(f.read_text())
                        break

        return artifacts

    def _handle_match_list(self):
        """List available match scenario artifacts (from slate + individual runs)."""
        scenarios_dir = Path(__file__).parent.parent / "output" / "scenarios"
        matches = {}

        if not scenarios_dir.exists():
            self._json_response({"matches": [], "count": 0})
            return

        # 1. Load from latest slate summary first
        latest_slate = scenarios_dir / "latest_slate.json"
        if latest_slate.exists():
            try:
                slate = json.loads(latest_slate.read_text())
                for m in slate.get("matches", []):
                    mid = m.get("id", "")
                    if mid and mid not in matches:
                        matches[mid] = {
                            "id": mid,
                            "label": m.get("label", mid.replace("_", " ")),
                            "timestamp": slate.get("generated_at", ""),
                            "source": "slate",
                        }
            except Exception:
                pass

        # 2. Also scan individual report files
        for f in sorted(scenarios_dir.glob("*_report.json"), reverse=True):
            name = f.stem.replace("_report", "")
            parts = name.rsplit("_", 2)
            if len(parts) >= 3:
                slug = "_".join(parts[:-2])
                timestamp = f"{parts[-2]}_{parts[-1]}"
            else:
                slug = name
                timestamp = ""

            if slug not in matches:
                report = json.loads(f.read_text())
                label = report.get("match_label", slug.replace("_", " "))
                matches[slug] = {
                    "id": slug,
                    "label": label,
                    "timestamp": timestamp,
                    "source": "individual",
                }

        self._json_response({
            "matches": list(matches.values()),
            "count": len(matches),
        })

    def _handle_match_section(self, match_id: str, section: str):
        """Handle match-specific data section."""
        artifacts = self._find_match_artifacts(match_id)

        if section == "overview":
            dossier = artifacts.get("dossier", {})
            overlay = artifacts.get("overlay", {})
            report = artifacts.get("report", {})

            player_a = dossier.get("player_a", {}).get("identity", {})
            player_b = dossier.get("player_b", {}).get("identity", {})
            tournament = dossier.get("tournament", {})

            self._json_response({
                "match": {
                    "player_a": player_a.get("name", "Unknown"),
                    "player_b": player_b.get("name", "Unknown"),
                    "ranking_a": player_a.get("ranking", 999),
                    "ranking_b": player_b.get("ranking", 999),
                    "elo_a": player_a.get("elo_overall", 1500),
                    "elo_b": player_b.get("elo_overall", 1500),
                    "tournament": tournament.get("tournament_name", ""),
                    "surface": tournament.get("surface", ""),
                    "round": tournament.get("round_name", ""),
                    "level": tournament.get("tournament_level", ""),
                },
                "market": {
                    "odds_a": dossier.get("player_a", {}).get("market_profile", {}).get("implied_prob", None),
                    "odds_b": dossier.get("player_b", {}).get("market_profile", {}).get("implied_prob", None),
                },
                "baseline": {
                    "prob_a": overlay.get("baseline_prob_a", 0.5),
                    "prob_b": overlay.get("baseline_prob_b", 0.5),
                    "confidence": overlay.get("baseline_confidence", "MEDIUM"),
                },
                "overlay": {
                    "prob_a": overlay.get("adjusted_prob_a", 0.5),
                    "prob_b": overlay.get("adjusted_prob_b", 0.5),
                    "confidence": overlay.get("adjusted_confidence", "MEDIUM"),
                    "delta": round(overlay.get("adjusted_prob_a", 0.5) - overlay.get("baseline_prob_a", 0.5), 4),
                },
                "decision": {
                    "action": overlay.get("adjusted_action", "SKIP"),
                    "skip_escalated": overlay.get("skip_escalated", False),
                },
                "data_quality": dossier.get("data_quality", 0),
                "has_artifacts": bool(artifacts),
            })

        elif section == "dossier":
            self._json_response(artifacts.get("dossier", {"error": "No dossier found"}))

        elif section == "scenario":
            self._json_response({
                "signals": artifacts.get("signals", {}),
                "overlay": artifacts.get("overlay", {}),
            })

        elif section == "graph":
            dossier = artifacts.get("dossier", {})
            # Build graph nodes and edges from dossier
            nodes = []
            edges = []

            if dossier:
                pa = dossier.get("player_a", {}).get("identity", {})
                pb = dossier.get("player_b", {}).get("identity", {})
                tournament = dossier.get("tournament", {})

                # Player nodes
                nodes.append({"id": "player_a", "label": pa.get("name", "Player A"), "type": "Player", "group": "player",
                              "data": {"ranking": pa.get("ranking"), "elo": pa.get("elo_overall")}})
                nodes.append({"id": "player_b", "label": pb.get("name", "Player B"), "type": "Player", "group": "player",
                              "data": {"ranking": pb.get("ranking"), "elo": pb.get("elo_overall")}})

                # Tournament node
                nodes.append({"id": "tournament", "label": tournament.get("tournament_name", "Tournament"),
                              "type": "Tournament", "group": "context"})

                # Surface node
                surface = tournament.get("surface", "")
                if surface:
                    nodes.append({"id": "surface", "label": surface, "type": "Surface", "group": "context"})
                    edges.append({"source": "tournament", "target": "surface", "label": "PLAYED_ON"})

                # Match node
                nodes.append({"id": "match", "label": f"{tournament.get('round_name', 'Match')}",
                              "type": "Match", "group": "match"})

                # H2H node
                h2h = dossier.get("h2h", {})
                if h2h.get("total_matches", 0) > 0:
                    nodes.append({"id": "h2h", "label": f"H2H: {h2h.get('a_wins', 0)}-{h2h.get('b_wins', 0)}",
                                  "type": "H2H", "group": "data"})
                    edges.append({"source": "player_a", "target": "h2h", "label": "H2H_RECORD"})
                    edges.append({"source": "player_b", "target": "h2h", "label": "H2H_RECORD"})

                # Market node
                nodes.append({"id": "market", "label": "Market", "type": "Market", "group": "market"})

                # Fatigue nodes
                phys_a = dossier.get("player_a", {}).get("physical_profile", {})
                phys_b = dossier.get("player_b", {}).get("physical_profile", {})
                if phys_a.get("fatigue_score", 0) > 0:
                    nodes.append({"id": "fatigue_a", "label": f"Fatigue: {phys_a['fatigue_score']:.0%}",
                                  "type": "Fatigue", "group": "risk"})
                    edges.append({"source": "player_a", "target": "fatigue_a", "label": "HAS_FATIGUE"})
                if phys_b.get("fatigue_score", 0) > 0:
                    nodes.append({"id": "fatigue_b", "label": f"Fatigue: {phys_b['fatigue_score']:.0%}",
                                  "type": "Fatigue", "group": "risk"})
                    edges.append({"source": "player_b", "target": "fatigue_b", "label": "HAS_FATIGUE"})

                # Edges
                edges.append({"source": "player_a", "target": "match", "label": "PLAYS_IN"})
                edges.append({"source": "player_b", "target": "match", "label": "PLAYS_IN"})
                edges.append({"source": "match", "target": "tournament", "label": "PART_OF"})
                edges.append({"source": "market", "target": "match", "label": "PRICES"})

            self._json_response({"nodes": nodes, "edges": edges})

        elif section == "report":
            self._json_response(artifacts.get("report", {"error": "No report found"}))

        elif section == "decision":
            overlay = artifacts.get("overlay", {})
            report = artifacts.get("report", {})
            self._json_response({
                "action": overlay.get("adjusted_action", "SKIP"),
                "baseline_action": overlay.get("baseline_action", "SKIP"),
                "skip_escalated": overlay.get("skip_escalated", False),
                "explanation": overlay.get("explanation", ""),
                "adjustments": overlay.get("adjustments", []),
                "baseline_prob_a": overlay.get("baseline_prob_a"),
                "adjusted_prob_a": overlay.get("adjusted_prob_a"),
                "baseline_confidence": overlay.get("baseline_confidence"),
                "adjusted_confidence": overlay.get("adjusted_confidence"),
            })

        else:
            self._json_response({
                "error": f"Unknown section: {section}",
                "available": ["overview", "dossier", "scenario", "graph", "report", "decision"],
            }, 404)

    # ── Slate API ──────────────────────────────────────────

    def _handle_slate(self):
        """Return the current slate: tomorrow's matches with predictions."""
        scenarios_dir = Path(__file__).parent.parent / "output" / "scenarios"
        latest_path = scenarios_dir / "latest_slate.json"

        if not latest_path.exists():
            self._json_response({
                "matches": [],
                "status": "no_slate",
                "message": "No slate generated yet. Run slate_runner.py or wait for supervisor.",
            })
            return

        try:
            slate = json.loads(latest_path.read_text())
            self._json_response(slate)
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _handle_slate_status(self):
        """Return slate runner status metadata."""
        scenarios_dir = Path(__file__).parent.parent / "output" / "scenarios"
        latest_path = scenarios_dir / "latest_slate.json"

        status = {
            "has_slate": latest_path.exists(),
            "generated_at": None,
            "date": None,
            "match_count": 0,
            "live_candidates": 0,
            "paper_candidates": 0,
            "stale": True,
        }

        if latest_path.exists():
            try:
                slate = json.loads(latest_path.read_text())
                status["generated_at"] = slate.get("generated_at")
                status["date"] = slate.get("date")
                status["match_count"] = slate.get("processed", 0)
                status["live_candidates"] = slate.get("live_candidates", 0)
                status["paper_candidates"] = slate.get("paper_candidates", 0)

                # Check freshness (< 4 hours = fresh)
                gen_at = slate.get("generated_at", "")
                if gen_at:
                    try:
                        gen_dt = datetime.fromisoformat(gen_at)
                        age_hours = (datetime.now() - gen_dt).total_seconds() / 3600
                        status["stale"] = age_hours > 4
                        status["age_hours"] = round(age_hours, 1)
                    except Exception:
                        pass
            except Exception:
                pass

        self._json_response(status)

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
