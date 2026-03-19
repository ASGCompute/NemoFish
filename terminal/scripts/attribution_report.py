#!/usr/bin/env python3
"""
NemoFish Daily Attribution Report
===================================
Analyzes each match from latest run(s) and produces attribution:
  - Winner prediction accuracy
  - Value side identification
  - Bet / No-bet decision
  - Outcome + CLV
  - Skip reason taxonomy
  - UNRESOLVED_PLAYER KPI

Usage:
  python3 terminal/scripts/attribution_report.py           # Today's runs
  python3 terminal/scripts/attribution_report.py --date 2026-03-16
"""

import sys
import json
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).parent.parent
RUNS_DIR = ROOT / "execution" / "runs"


def load_runs_for_date(target_date: str = None) -> list:
    """Load all run summaries for a given date."""
    if target_date is None:
        target_date = date.today().strftime("%Y%m%d")
    else:
        target_date = target_date.replace("-", "")

    runs = []
    if not RUNS_DIR.exists():
        return runs

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if run_dir.name.startswith(target_date):
            summary_path = run_dir / "run_summary.json"
            risk_path = run_dir / "risk_decisions.json"
            fixtures_path = run_dir / "fixtures.json"

            run_data = {"dir": run_dir.name}
            for f, key in [(summary_path, "summary"), (risk_path, "decisions"),
                           (fixtures_path, "fixtures")]:
                if f.exists():
                    try:
                        run_data[key] = json.loads(f.read_text())
                    except json.JSONDecodeError:
                        pass
            runs.append(run_data)

    return runs


def generate_attribution(runs: list) -> dict:
    """Generate attribution report from runs."""
    report = {
        "date": date.today().isoformat(),
        "total_cycles": len(runs),
        "matches": {},
        "kpis": {
            "total_fixtures": 0,
            "with_odds": 0,
            "unresolved_players": 0,
            "unresolved_pct": 0,
            "bets_placed": 0,
            "skip_reasons": {
                "no_odds": 0,
                "unresolved_player": 0,
                "no_edge": 0,
                "low_confidence": 0,
                "strategy_filter": 0,
            },
        },
    }

    all_unresolved = set()

    for run in runs:
        decisions = run.get("decisions", [])
        summary = run.get("summary", {})

        report["kpis"]["total_fixtures"] += summary.get("fixtures_scanned", 0)
        report["kpis"]["with_odds"] += summary.get("odds_matches", 0)
        report["kpis"]["bets_placed"] += summary.get("bets_executed", 0)

        for d in decisions:
            match = d.get("match", "unknown")
            action = d.get("action", "SKIP")
            reason = d.get("reason", "")

            # Classify skip reason
            if "UNRESOLVED" in reason or "UNRESOLVED" in match:
                report["kpis"]["skip_reasons"]["unresolved_player"] += 1
                all_unresolved.add(match)
            elif d.get("odds_source") == "NO_ODDS":
                report["kpis"]["skip_reasons"]["no_odds"] += 1
            elif d.get("edge") is not None and float(d.get("edge", 0)) <= 0:
                report["kpis"]["skip_reasons"]["no_edge"] += 1
            elif action == "SKIP":
                report["kpis"]["skip_reasons"]["low_confidence"] += 1

            # Per-match attribution
            if match not in report["matches"]:
                report["matches"][match] = {
                    "action": action,
                    "prob_a": d.get("prob_a"),
                    "prob_b": d.get("prob_b"),
                    "edge": d.get("edge"),
                    "confidence": d.get("confidence"),
                    "odds_source": d.get("odds_source", "NO_ODDS"),
                    "kelly": d.get("kelly"),
                    "issue_type": _classify_issue(d),
                    # Filled by resolution later:
                    "actual_winner": None,
                    "prediction_correct": None,
                    "clv": None,
                }

    # UNRESOLVED_PLAYER KPI
    report["kpis"]["unresolved_players"] = len(all_unresolved)
    total = report["kpis"]["total_fixtures"]
    if total > 0:
        report["kpis"]["unresolved_pct"] = round(len(all_unresolved) / total * 100, 1)

    return report


def _classify_issue(decision: dict) -> str:
    """Classify the issue type for a skipped match."""
    reason = decision.get("reason", "")
    if "UNRESOLVED" in reason:
        return "resolver_issue"
    if decision.get("odds_source") == "NO_ODDS":
        return "data_issue"
    if decision.get("edge") is not None and float(decision.get("edge", 0)) <= 0:
        return "strategy_issue"
    if decision.get("action") == "BET":
        return "none"
    return "execution_issue"


def print_report(report: dict):
    """Print attribution report to console."""
    kpis = report["kpis"]
    print(f"\n{'═' * 65}")
    print(f"  📊 DAILY ATTRIBUTION REPORT — {report['date']}")
    print(f"{'═' * 65}")

    print(f"\n  📈 KPIs")
    print(f"  {'─' * 55}")
    print(f"  Cycles:                {report['total_cycles']}")
    print(f"  Total fixtures:        {kpis['total_fixtures']}")
    print(f"  With real odds:        {kpis['with_odds']}")
    print(f"  Bets placed:           {kpis['bets_placed']}")
    print(f"  UNRESOLVED_PLAYER:     {kpis['unresolved_players']} ({kpis['unresolved_pct']}%)")

    print(f"\n  🚫 Skip Reasons")
    print(f"  {'─' * 55}")
    for reason, count in kpis["skip_reasons"].items():
        print(f"  {reason:25s} {count}")

    # Issue types
    issues = {}
    for m, data in report["matches"].items():
        it = data.get("issue_type", "unknown")
        issues[it] = issues.get(it, 0) + 1

    print(f"\n  🔍 Issue Taxonomy")
    print(f"  {'─' * 55}")
    for issue, count in sorted(issues.items(), key=lambda x: -x[1]):
        print(f"  {issue:25s} {count}")

    print(f"\n{'═' * 65}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NemoFish Daily Attribution Report")
    parser.add_argument("--date", type=str, default=None, help="Date to report on (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    target = args.date.replace("-", "") if args.date else None
    runs = load_runs_for_date(target)

    if not runs:
        print(f"No runs found for {args.date or 'today'}")
        sys.exit(0)

    report = generate_attribution(runs)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)

    # Save report
    report_dir = ROOT / "execution" / "attribution"
    report_dir.mkdir(parents=True, exist_ok=True)
    d = report["date"].replace("-", "")
    path = report_dir / f"attribution_{d}.json"
    path.write_text(json.dumps(report, indent=2, default=str))
    print(f"  💾 Report saved: {path}")


if __name__ == "__main__":
    main()
