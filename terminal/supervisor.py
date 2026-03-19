#!/usr/bin/env python3
"""
NemoFish Supervisor — 24/7 Continuous Revenue Engine
=====================================================
Runs live_runner in a loop:
  - 10 min intervals during match windows (10:00–04:00 UTC)
  - 30 min intervals outside match windows
  - Auto-restart on crash
  - Founder summary after each cycle
  - Shadow mode for all strategies in parallel
  - Reconciliation after each trade

Usage:
  python3 terminal/supervisor.py                  # Full live canary
  python3 terminal/supervisor.py --shadow-only    # Shadow mode only (no money)
  python3 terminal/supervisor.py --dry-run        # Show what would happen, don't execute
"""

import sys
import os
import json
import time
import subprocess
import signal
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).parent
EXECUTION_DIR = ROOT / "execution"
RUNS_DIR = EXECUTION_DIR / "runs"
SUMMARY_DIR = EXECUTION_DIR / "founder_summaries"
SHADOW_DIR = EXECUTION_DIR / "shadow"

# === Load .env ===
_ENV_PATH = ROOT.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


# === Config ===
MATCH_WINDOW_START = 10  # UTC hour (covers ATP Americas + Europe + Asia)
MATCH_WINDOW_END = 4     # UTC hour (next day)
INTERVAL_ACTIVE = 600    # 10 minutes during match windows
INTERVAL_IDLE = 1800     # 30 minutes outside match windows
MAX_CONSECUTIVE_ERRORS = 5
LIVE_STRATEGY = "value_confirmation"
SLATE_INTERVAL = 14400   # 4 hours between slate rebuilds


def is_match_window() -> bool:
    """Check if current time is within active match window."""
    hour = datetime.utcnow().hour
    # Window: 10:00 UTC → 04:00 UTC next day (wraps midnight)
    if MATCH_WINDOW_START <= MATCH_WINDOW_END:
        return MATCH_WINDOW_START <= hour < MATCH_WINDOW_END
    else:
        return hour >= MATCH_WINDOW_START or hour < MATCH_WINDOW_END


def run_live_cycle(scan_only: bool = False) -> dict:
    """
    Run one live canary cycle with ValueConfirmation.
    Returns parsed run summary.
    """
    cmd = [
        sys.executable, str(ROOT / "live_runner.py"),
        "--live",
        "--with-strategies",
        "--strategies", LIVE_STRATEGY,
    ]
    if scan_only:
        cmd.append("--scan-only")

    print(f"\n{'━' * 60}")
    print(f"  🔴 LIVE CANARY CYCLE — {datetime.now().strftime('%H:%M:%S')}")
    print(f"  Strategy: {LIVE_STRATEGY}")
    print(f"  Mode: {'SCAN-ONLY' if scan_only else 'LIVE EXECUTION'}")
    print(f"{'━' * 60}\n")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=300,  # 5 min max per cycle
        env=os.environ.copy(),
    )

    # Print output
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        for line in result.stderr.splitlines():
            if "NotOpenSSLWarning" not in line:
                print(f"  ⚠️  {line}", file=sys.stderr)

    # Parse last_run.json
    last_run_path = EXECUTION_DIR / "last_run.json"
    try:
        summary = json.loads(last_run_path.read_text())
        summary["exit_code"] = result.returncode
        return summary
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "exit_code": result.returncode,
            "error": "Could not parse last_run.json",
            "timestamp": datetime.now().isoformat(),
        }


def run_shadow_cycle() -> dict:
    """
    Run shadow cycle: all strategies, all matches, no money (PAPER mode).
    """
    cmd = [
        sys.executable, str(ROOT / "live_runner.py"),
        "--with-strategies",  # no --live = PAPER mode
        "--scan-only",        # never execute in shadow
    ]

    print(f"\n{'━' * 60}")
    print(f"  👻 SHADOW CYCLE — {datetime.now().strftime('%H:%M:%S')}")
    print(f"  All strategies, PAPER mode, scan-only")
    print(f"{'━' * 60}\n")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=300,
        env=os.environ.copy(),
    )

    # Save shadow output
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    shadow_out = SHADOW_DIR / f"shadow_{ts}.log"
    shadow_out.write_text(result.stdout or "")

    # Parse shadow results
    last_run_path = EXECUTION_DIR / "last_run.json"
    try:
        return json.loads(last_run_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "shadow_complete", "timestamp": datetime.now().isoformat()}


def run_slate_cycle(target_date: str = None, dry_run: bool = True) -> dict:
    """
    Run the NemoFish Slate Runner — batch scenario engine for tomorrow's matches.
    """
    print(f"\n{'━' * 60}")
    print(f"  🐠 SLATE CYCLE — {datetime.now().strftime('%H:%M:%S')}")
    print(f"  Date: {target_date or 'tomorrow'}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE LLM'}")
    print(f"{'━' * 60}\n")

    try:
        sys.path.insert(0, str(ROOT / "intelligence"))
        from intelligence.slate_runner import run_slate
        result = run_slate(target_date=target_date, dry_run=dry_run)
        return result
    except Exception as e:
        print(f"  ❌ Slate cycle error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


def save_founder_summary(live_result: dict, shadow_result: dict = None, cycle_num: int = 0):
    """
    Save concise founder summary after each cycle.
    """
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Extract key metrics
    fixtures = live_result.get("fixtures_scanned", 0)
    predictions = live_result.get("predictions_made", 0)
    bets = live_result.get("bets_executed", 0)
    results = live_result.get("results", [])
    balance = live_result.get("daily_summary", {})
    odds_matches = live_result.get("odds_matches", 0)

    # Count skip reasons
    skip_reasons = {"NO_ODDS": 0, "UNRESOLVED": 0, "NO_EDGE": 0, "LOW_CONFIDENCE": 0}
    # We'll parse from the risk decisions if available
    risk_path = None
    runs = sorted(RUNS_DIR.iterdir()) if RUNS_DIR.exists() else []
    if runs:
        latest_run = runs[-1]
        risk_file = latest_run / "risk_decisions.json"
        if risk_file.exists():
            try:
                decisions = json.loads(risk_file.read_text())
                for d in decisions:
                    if d.get("action") == "SKIP":
                        reason = d.get("reason", "")
                        odds_src = d.get("odds_source", "")
                        if "UNRESOLVED" in reason:
                            skip_reasons["UNRESOLVED"] += 1
                        elif odds_src == "NO_ODDS" or "NO_ODDS" in str(d):
                            skip_reasons["NO_ODDS"] += 1
                        elif d.get("edge", 0) and float(d.get("edge", 0)) <= 0:
                            skip_reasons["NO_EDGE"] += 1
                        else:
                            skip_reasons["LOW_CONFIDENCE"] += 1
            except Exception:
                pass

    summary = {
        "cycle": cycle_num,
        "timestamp": datetime.now().isoformat(),
        "match_window": is_match_window(),
        "live": {
            "strategy": LIVE_STRATEGY,
            "fixtures_scanned": fixtures,
            "with_odds": odds_matches,
            "qualified_bets": bets,
            "executed": bets,
            "skip_reasons": skip_reasons,
            "balance": balance,
            "open_positions": len([r for r in results if r.get("status") == "OPEN"]),
        },
        "shadow": {
            "ran": shadow_result is not None,
            "fixtures": shadow_result.get("fixtures_scanned", 0) if shadow_result else 0,
            "predictions": shadow_result.get("predictions_made", 0) if shadow_result else 0,
        },
    }

    # Save JSON
    path = SUMMARY_DIR / f"summary_{ts}.json"
    path.write_text(json.dumps(summary, indent=2, default=str))

    # Also save latest
    latest = SUMMARY_DIR / "latest.json"
    latest.write_text(json.dumps(summary, indent=2, default=str))

    # Console output
    print(f"\n{'═' * 60}")
    print(f"  📊 FOUNDER SUMMARY — Cycle #{cycle_num}")
    print(f"  {'─' * 56}")
    print(f"  Fixtures scanned:  {fixtures}")
    print(f"  With real odds:    {odds_matches}")
    print(f"  Qualified bets:    {bets}")
    print(f"  Executed:          {bets}")
    print(f"  Skip: NO_ODDS={skip_reasons['NO_ODDS']}, UNRESOLVED={skip_reasons['UNRESOLVED']}, "
          f"NO_EDGE={skip_reasons['NO_EDGE']}, LOW_CONF={skip_reasons['LOW_CONFIDENCE']}")
    if balance:
        print(f"  Balance:           {balance}")
    print(f"  Open positions:    {len([r for r in results if r.get('status') == 'OPEN'])}")
    if shadow_result:
        print(f"  Shadow:            {shadow_result.get('fixtures_scanned', 0)} fixtures, "
              f"{shadow_result.get('predictions_made', 0)} predictions")
    print(f"{'═' * 60}")

    return summary


def save_reconciliation(trade_result: dict, cycle_num: int):
    """
    Save trade reconciliation data after each executed bet.
    """
    recon_dir = EXECUTION_DIR / "reconciliation"
    recon_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    recon = {
        "cycle": cycle_num,
        "timestamp": datetime.now().isoformat(),
        "order_response": trade_result.get("order_response", {}),
        "execution_price": trade_result.get("execution_price"),
        "market_snapshot": trade_result.get("market_snapshot", {}),
        "strategy": LIVE_STRATEGY,
        "match": trade_result.get("match", ""),
        "side": trade_result.get("side", ""),
        "amount": trade_result.get("amount", 0),
        # These get filled in later by resolution
        "closing_price": None,
        "clv": None,
        "resolved_pnl": None,
        "resolved_at": None,
    }

    path = recon_dir / f"recon_{ts}.json"
    path.write_text(json.dumps(recon, indent=2, default=str))
    print(f"  📋 Reconciliation saved: {path.name}")
    return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NemoFish 24/7 Supervisor")
    parser.add_argument("--shadow-only", action="store_true", help="Shadow mode only (no money)")
    parser.add_argument("--dry-run", action="store_true", help="Show intervals, don't execute")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--slate-only", action="store_true", help="Only run slate cycle, no live/shadow")
    args = parser.parse_args()

    # Graceful shutdown
    running = [True]
    def handle_signal(sig, frame):
        print(f"\n\n🛑 Supervisor stopping (signal {sig})...")
        running[0] = False
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print("═" * 60)
    print("  🐡 NEMOFISH SUPERVISOR — 24/7 Revenue Engine")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Live strategy: {LIVE_STRATEGY}")
    print(f"  Limits: $1/bet, $4/day, 1 concurrent")
    print(f"  Active interval: {INTERVAL_ACTIVE // 60}min | Idle: {INTERVAL_IDLE // 60}min")
    if args.shadow_only:
        print("  Mode: SHADOW ONLY (no money)")
    elif args.dry_run:
        print("  Mode: DRY RUN (no execution)")
    else:
        print("  Mode: 🔴 LIVE CANARY + SHADOW")
    print("═" * 60)

    cycle = 0
    consecutive_errors = 0
    last_slate_run = 0  # epoch seconds

    while running[0]:
        cycle += 1
        active = is_match_window()
        interval = INTERVAL_ACTIVE if active else INTERVAL_IDLE

        print(f"\n⏰ Cycle #{cycle} | {'🟢 Match window' if active else '🟡 Idle window'} | "
              f"Next in {interval // 60}min")

        if args.dry_run:
            print("  [DRY RUN] Would run live + shadow + slate cycle")
            if args.once:
                break
            time.sleep(interval)
            continue

        try:
            # Slate cycle (every 4 hours or on first run)
            now_epoch = time.time()
            should_run_slate = (now_epoch - last_slate_run) >= SLATE_INTERVAL

            if should_run_slate or args.slate_only:
                slate_result = run_slate_cycle(dry_run=True)
                last_slate_run = time.time()
                print(f"  🐠 Slate: {slate_result.get('processed', 0)} matches processed")

                if args.slate_only:
                    if args.once:
                        break
                    time.sleep(interval)
                    continue
            if args.shadow_only:
                live_result = run_live_cycle(scan_only=True)
            else:
                live_result = run_live_cycle(scan_only=False)

            # Shadow all strategies
            shadow_result = run_shadow_cycle()

            # Founder summary
            summary = save_founder_summary(live_result, shadow_result, cycle)

            # Reconciliation for any executed trades
            results = live_result.get("results", [])
            for trade in results:
                if trade.get("status") in ("FILLED", "PARTIAL"):
                    save_reconciliation(trade, cycle)

            consecutive_errors = 0

        except subprocess.TimeoutExpired:
            print(f"  ⚠️  Cycle #{cycle} timed out (5min limit)")
            consecutive_errors += 1
        except Exception as e:
            print(f"  ❌ Cycle #{cycle} error: {e}")
            consecutive_errors += 1

        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            print(f"\n🛑 {MAX_CONSECUTIVE_ERRORS} consecutive errors — supervisor pausing for 1 hour")
            time.sleep(3600)
            consecutive_errors = 0

        if args.once:
            print("\n  [--once] Single cycle complete, exiting.")
            break

        # Wait for next cycle
        if running[0]:
            next_run = datetime.now() + timedelta(seconds=interval)
            print(f"\n  ⏳ Next cycle at {next_run.strftime('%H:%M:%S')} "
                  f"({'active' if active else 'idle'} window)")
            # Interruptible sleep
            for _ in range(interval):
                if not running[0]:
                    break
                time.sleep(1)

    print("\n🐡 Supervisor stopped.")


if __name__ == "__main__":
    main()
