"""
Data Health Layer — Freshness, Schema, and Connectivity Checks
================================================================
Validates all data sources before pipeline execution.
Called at live_runner startup (Step 0) and by /api/health.

Usage:
  python3 terminal/feeds/data_health.py          # CLI health check
  from feeds.data_health import check_all        # Programmatic
"""

import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional

ROOT = Path(__file__).parent.parent

# ─── Result Types ───────────────────────────────────────────────

@dataclass
class SourceHealth:
    """Health status of a single data source."""
    name: str
    status: str              # "green" | "yellow" | "red"
    message: str
    last_updated: str = ""   # ISO timestamp or description
    record_count: int = 0
    latency_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("green", "yellow")


@dataclass
class DataHealth:
    """Aggregated health of all data sources."""
    overall: str = "green"    # worst of all sources
    sources: List[SourceHealth] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "timestamp": self.timestamp,
            "sources": [asdict(s) for s in self.sources],
        }


# ─── Individual Checks ─────────────────────────────────────────

def check_sackmann() -> SourceHealth:
    """Verify JeffSackmann ATP+WTA CSVs exist and are fresh."""
    atp_dir = ROOT / "data" / "tennis" / "tennis_atp"
    wta_dir = ROOT / "data" / "tennis" / "tennis_wta"

    if not atp_dir.exists():
        return SourceHealth(
            name="JeffSackmann ATP",
            status="red",
            message=f"Directory not found: {atp_dir}",
        )

    current_year = datetime.now().year
    # Check for current or recent year file
    recent_csvs = sorted(atp_dir.glob(f"atp_matches_{current_year}*.csv"))
    if not recent_csvs:
        recent_csvs = sorted(atp_dir.glob(f"atp_matches_{current_year - 1}*.csv"))

    if not recent_csvs:
        return SourceHealth(
            name="JeffSackmann ATP",
            status="red",
            message=f"No match files for {current_year} or {current_year - 1}",
        )

    latest = recent_csvs[-1]
    mtime = datetime.fromtimestamp(latest.stat().st_mtime)
    age_days = (datetime.now() - mtime).days

    # Count total CSV files
    all_csvs = list(atp_dir.glob("atp_matches_*.csv"))
    wta_csvs = list(wta_dir.glob("wta_matches_*.csv")) if wta_dir.exists() else []

    if age_days > 30:
        status = "yellow"
        msg = f"Data is {age_days} days old — consider git pull"
    else:
        status = "green"
        msg = f"Fresh ({age_days}d old)"

    return SourceHealth(
        name="JeffSackmann ATP+WTA",
        status=status,
        message=msg,
        last_updated=mtime.isoformat(),
        record_count=len(all_csvs) + len(wta_csvs),
    )


def check_api_tennis() -> SourceHealth:
    """Test api-tennis.com API key and connectivity."""
    key = os.environ.get("API_TENNIS_KEY", "")
    if not key:
        return SourceHealth(
            name="api-tennis.com",
            status="red",
            message="API_TENNIS_KEY not set in .env",
        )

    try:
        import urllib.request
        import urllib.error
        import json

        url = f"https://api.api-tennis.com/tennis/?method=get&event_type=live&APIkey={key}"
        start = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "NemoFish/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - start) * 1000

        if data.get("success", 0) == 1:
            results = data.get("result", [])
            return SourceHealth(
                name="api-tennis.com",
                status="green",
                message=f"Connected — {len(results)} live events",
                latency_ms=round(latency, 1),
                record_count=len(results),
            )
        else:
            return SourceHealth(
                name="api-tennis.com",
                status="yellow",
                message=f"API returned success=0: {data.get('error', 'unknown')}",
                latency_ms=round(latency, 1),
            )
    except urllib.error.HTTPError as e:
        # Server-side errors (5xx) are transient — degrade, don't block
        if 500 <= e.code < 600:
            return SourceHealth(
                name="api-tennis.com",
                status="yellow",
                message=f"Provider degraded (HTTP {e.code}) — transient, pipeline can retry",
            )
        return SourceHealth(
            name="api-tennis.com",
            status="red",
            message=f"HTTP {e.code}: {str(e)[:60]}",
        )
    except Exception as e:
        return SourceHealth(
            name="api-tennis.com",
            status="red",
            message=f"Connection failed: {str(e)[:80]}",
        )


def check_sportradar() -> SourceHealth:
    """Test Sportradar API key presence."""
    key = os.environ.get("SPORTRADAR_API_KEY", "")
    if not key:
        return SourceHealth(
            name="Sportradar",
            status="yellow",
            message="SPORTRADAR_API_KEY not set — rankings unavailable",
        )

    # Don't hit the API to save quota, just validate key format
    return SourceHealth(
        name="Sportradar",
        status="green",
        message=f"Key configured ({key[:8]}...)",
    )


def check_odds_api() -> SourceHealth:
    """Test The Odds API key and connectivity."""
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        return SourceHealth(
            name="The Odds API",
            status="yellow",
            message="ODDS_API_KEY not set — real-time odds unavailable",
        )

    try:
        import urllib.request
        import json

        url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
        start = time.time()
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - start) * 1000
            remaining = resp.headers.get("x-requests-remaining", "?")

        tennis_sports = [s for s in data if "tennis" in s.get("key", "").lower()]
        return SourceHealth(
            name="The Odds API",
            status="green",
            message=f"Connected — {len(tennis_sports)} tennis sports, {remaining} requests remaining",
            latency_ms=round(latency, 1),
            record_count=len(tennis_sports),
        )
    except Exception as e:
        return SourceHealth(
            name="The Odds API",
            status="red",
            message=f"Connection failed: {str(e)[:80]}",
        )


def check_polymarket() -> SourceHealth:
    """Test Polymarket gamma API for tennis events.
    
    Uses the same tag_slug parameter as production discovery
    (see polymarket_live.py search_markets()).
    """
    key = os.environ.get("POLYMARKET_API_KEY", "")
    wallet = os.environ.get("POLYMARKET_WALLET", "")

    if not key:
        return SourceHealth(
            name="Polymarket",
            status="red",
            message="POLYMARKET_API_KEY not set",
        )

    try:
        import urllib.request
        import json

        # Use tag_slug= (not tag=) — same as production path in polymarket_live.py
        url = "https://gamma-api.polymarket.com/events?tag_slug=tennis&active=true&closed=false&limit=5"
        start = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "NemoFish/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - start) * 1000

        event_count = len(data) if isinstance(data, list) else 0
        wallet_msg = f", wallet: {wallet[:10]}..." if wallet else ", ⚠️ no wallet"
        return SourceHealth(
            name="Polymarket",
            status="green" if event_count > 0 else "yellow",
            message=f"{event_count} open tennis events{wallet_msg}",
            latency_ms=round(latency, 1),
            record_count=event_count,
        )
    except Exception as e:
        return SourceHealth(
            name="Polymarket",
            status="red",
            message=f"Connection failed: {str(e)[:80]}",
        )


def check_llm() -> SourceHealth:
    """Verify LLM API key is configured."""
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL_NAME", "not set")
    if not key:
        return SourceHealth(
            name="LLM (Swarm)",
            status="red",
            message="LLM_API_KEY not set — swarm agents unavailable",
        )
    return SourceHealth(
        name="LLM (Swarm)",
        status="green",
        message=f"Configured: {model}",
    )


def check_last_run() -> SourceHealth:
    """Check if there's a recent run artifact."""
    last_run = ROOT / "execution" / "last_run.json"
    if not last_run.exists():
        return SourceHealth(
            name="Last Run",
            status="yellow",
            message="No run artifacts yet — run live_runner.py first",
        )

    import json
    try:
        data = json.loads(last_run.read_text())
        ts = data.get("timestamp", "")
        if ts:
            run_time = datetime.fromisoformat(ts)
            age_hours = (datetime.now() - run_time).total_seconds() / 3600
            return SourceHealth(
                name="Last Run",
                status="green" if age_hours < 24 else "yellow",
                message=f"{age_hours:.1f}h ago" + (f" — {data.get('status', '')}" if data.get('status') else ""),
                last_updated=ts,
            )
    except Exception:
        pass

    return SourceHealth(
        name="Last Run",
        status="yellow",
        message="Run artifact exists but unreadable",
    )


# ─── Aggregated Check ──────────────────────────────────────────

def check_all(live_api_checks: bool = True) -> DataHealth:
    """
    Run all data health checks.

    Args:
        live_api_checks: If True, hit external APIs (slower but thorough).
                         If False, only check local data and env vars.
    """
    # Load .env if not already loaded
    env_path = ROOT.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    sources: List[SourceHealth] = []

    # Always check local data
    sources.append(check_sackmann())
    sources.append(check_llm())
    sources.append(check_last_run())

    if live_api_checks:
        sources.append(check_api_tennis())
        sources.append(check_odds_api())
        sources.append(check_polymarket())
        sources.append(check_sportradar())
    else:
        # Just check env vars
        sources.append(check_sportradar())

    # Determine overall status
    statuses = [s.status for s in sources]
    if "red" in statuses:
        overall = "red"
    elif "yellow" in statuses:
        overall = "yellow"
    else:
        overall = "green"

    return DataHealth(
        overall=overall,
        sources=sources,
        timestamp=datetime.now().isoformat(),
    )


# ─── CLI ────────────────────────────────────────────────────────

STATUS_ICONS = {"green": "✅", "yellow": "⚠️ ", "red": "❌"}

def _print_health(health: DataHealth):
    """Pretty-print health status to terminal."""
    overall_icon = STATUS_ICONS.get(health.overall, "?")
    print(f"\n{'═' * 55}")
    print(f"  🐡 NEMOFISH DATA HEALTH — {overall_icon} {health.overall.upper()}")
    print(f"  {health.timestamp}")
    print(f"{'═' * 55}")

    for s in health.sources:
        icon = STATUS_ICONS.get(s.status, "?")
        latency = f" ({s.latency_ms:.0f}ms)" if s.latency_ms > 0 else ""
        count = f" [{s.record_count}]" if s.record_count > 0 else ""
        print(f"  {icon} {s.name:.<25} {s.message}{latency}{count}")

    print(f"{'─' * 55}\n")


if __name__ == "__main__":
    import sys
    fast = "--fast" in sys.argv
    health = check_all(live_api_checks=not fast)
    _print_health(health)
    sys.exit(0 if health.overall != "red" else 1)
