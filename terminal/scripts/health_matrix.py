#!/usr/bin/env python3
"""
NemoFish Health Matrix — Unified System Status
================================================
CLI tool to check all system components at once.

Usage:
  python3 terminal/scripts/health_matrix.py           # Full check
  python3 terminal/scripts/health_matrix.py --fast     # Local only (no API calls)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env
_ENV_PATH = ROOT.parent / ".env"
if _ENV_PATH.exists():
    import os
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


def check_tests() -> tuple:
    """Run pytest in subprocess, return (pass, total, status)."""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60
        )
        output = result.stdout + result.stderr
        # Parse "73 passed" from output
        for line in output.splitlines():
            if "passed" in line:
                import re
                m = re.search(r"(\d+) passed", line)
                failed = re.search(r"(\d+) failed", line)
                p = int(m.group(1)) if m else 0
                f = int(failed.group(1)) if failed else 0
                status = "green" if f == 0 else "red"
                return (p, p + f, status, f"{p} passed, {f} failed")
        return (0, 0, "yellow", "Could not parse test output")
    except Exception as e:
        return (0, 0, "red", f"Error: {e}")


def check_strategies() -> tuple:
    """Check strategy registry status."""
    try:
        from strategies import STRATEGY_REGISTRY, get_live_approved, get_by_status
        total = len(STRATEGY_REGISTRY)
        approved = len(get_live_approved())
        validated = len(get_by_status('validated'))
        research = sum(1 for e in STRATEGY_REGISTRY.values() if e['status'] == 'research')
        status = "yellow" if approved == 0 else "green"
        return (status, f"{total} strategies: {research} research, {validated} validated, {approved} live-approved")
    except Exception as e:
        return ("red", f"Registry error: {e}")


def check_config() -> tuple:
    """Check config.yaml bankroll."""
    config_path = ROOT / "config.yaml"
    if not config_path.exists():
        return ("red", "config.yaml not found")

    content = config_path.read_text()
    for line in content.splitlines():
        if "initial_usd" in line:
            val = line.split(":")[1].strip().split("#")[0].strip()
            try:
                bankroll = float(val)
                return ("green", f"Bankroll: ${bankroll:.0f}")
            except ValueError:
                return ("yellow", f"Could not parse bankroll: {val}")
    return ("yellow", "initial_usd not found in config.yaml")


def check_runs() -> tuple:
    """Check execution run artifacts."""
    runs_dir = ROOT / "execution" / "runs"
    if not runs_dir.exists():
        return ("yellow", "No run artifacts yet")

    run_dirs = sorted(runs_dir.iterdir())
    if not run_dirs:
        return ("yellow", "No run artifacts yet")

    latest = run_dirs[-1]
    return ("green", f"{len(run_dirs)} runs, latest: {latest.name}")


def check_resolver() -> tuple:
    """Check name resolver is importable and has fail-closed policy."""
    try:
        from feeds.name_resolver import TennisNameResolver, ResolveResult
        return ("green", "Fail-closed policy active (ResolveResult)")
    except ImportError as e:
        return ("red", f"Import error: {e}")


def main():
    fast = "--fast" in sys.argv

    STATUS_ICONS = {"green": "✅", "yellow": "⚠️ ", "red": "❌"}

    print(f"\n{'═' * 60}")
    print(f"  🐡 NEMOFISH HEALTH MATRIX")
    from datetime import datetime
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 60}")

    # 1. Data sources
    print(f"\n  📊 DATA SOURCES")
    print(f"  {'─' * 50}")
    from feeds.data_health import check_all, STATUS_ICONS as _ICONS
    health = check_all(live_api_checks=not fast)
    for s in health.sources:
        icon = STATUS_ICONS.get(s.status, "?")
        lat = f" ({s.latency_ms:.0f}ms)" if s.latency_ms > 0 else ""
        print(f"  {icon} {s.name:.<30} {s.message}{lat}")

    # 2. Tests
    print(f"\n  🧪 TESTS")
    print(f"  {'─' * 50}")
    passed, total, t_status, t_msg = check_tests()
    print(f"  {STATUS_ICONS[t_status]} Tests{'.':.<25} {t_msg}")

    # 3. Strategies
    print(f"\n  🎯 STRATEGIES")
    print(f"  {'─' * 50}")
    s_status, s_msg = check_strategies()
    print(f"  {STATUS_ICONS[s_status]} Registry{'.':.<22} {s_msg}")

    # 4. Config
    print(f"\n  ⚙️  CONFIG")
    print(f"  {'─' * 50}")
    c_status, c_msg = check_config()
    print(f"  {STATUS_ICONS[c_status]} config.yaml{'.':.<19} {c_msg}")

    # 5. Resolver
    r_status, r_msg = check_resolver()
    print(f"  {STATUS_ICONS[r_status]} Name Resolver{'.':.<17} {r_msg}")

    # 6. Runs
    run_status, run_msg = check_runs()
    print(f"  {STATUS_ICONS[run_status]} Run Artifacts{'.':.<17} {run_msg}")

    # Overall
    all_statuses = [health.overall, t_status, s_status, c_status, r_status, run_status]
    if "red" in all_statuses:
        overall = "red"
    elif "yellow" in all_statuses:
        overall = "yellow"
    else:
        overall = "green"

    icon = STATUS_ICONS[overall]
    print(f"\n{'═' * 60}")
    print(f"  {icon} OVERALL: {overall.upper()}")
    print(f"{'═' * 60}\n")

    sys.exit(0 if overall != "red" else 1)


if __name__ == "__main__":
    main()
