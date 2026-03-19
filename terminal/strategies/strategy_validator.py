"""
Strategy Validator — Honest Validation Criteria
=================================================
Pure function: takes backtest metrics → returns pass/fail with reasons.

Validation thresholds for promotion from 'research' → 'validated':
  1. Sample size: N >= 50 bets
  2. ROI: > 0% (profitable after vig)
  3. Max drawdown: < 50% of total wagered
  4. Sharpe ratio (per-bet): > 0
  5. Leakage-free: train year < test year (enforced by backtester)

'validated' → 'live-approved' requires founder sign-off (manual).
"""

from dataclasses import dataclass, field
from typing import List, Optional


# === Thresholds ===
MIN_SAMPLE_SIZE = 50
MIN_ROI_PCT = 0.0           # Must be strictly positive
MAX_DRAWDOWN_PCT = 50.0     # Max DD < 50% of wagered
MIN_SHARPE = 0.0            # Must be strictly positive


@dataclass
class ValidationResult:
    """Result of validating a strategy against thresholds."""
    strategy_name: str
    passes: bool
    status: str              # "validated" or "research"
    fail_reasons: List[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        if self.passes:
            return f"✅ {self.strategy_name}: VALIDATED (ROI {self.metrics.get('roi', 0):+.1f}%, N={self.metrics.get('bets', 0)})"
        reasons = "; ".join(self.fail_reasons)
        return f"❌ {self.strategy_name}: RESEARCH ({reasons})"


def validate_strategy(
    name: str,
    bets: int,
    wins: int,
    roi: float,
    sharpe: float,
    max_drawdown: float,
    wagered: float,
    pnl: float,
) -> ValidationResult:
    """
    Evaluate a strategy against validation criteria.

    Args:
        name: Strategy name
        bets: Total number of bets placed
        wins: Number of winning bets
        roi: Return on investment (%)
        sharpe: Sharpe ratio (per-bet)
        max_drawdown: Maximum drawdown in dollars
        wagered: Total amount wagered in dollars
        pnl: Total P&L in dollars

    Returns:
        ValidationResult with pass/fail and reasons
    """
    fail_reasons = []

    # 1. Sample size
    if bets < MIN_SAMPLE_SIZE:
        fail_reasons.append(f"sample_size: {bets} < {MIN_SAMPLE_SIZE}")

    # 2. ROI
    if roi <= MIN_ROI_PCT:
        fail_reasons.append(f"roi: {roi:+.1f}% <= {MIN_ROI_PCT}%")

    # 3. Max drawdown relative to wagered
    if wagered > 0:
        dd_pct = (max_drawdown / wagered) * 100
        if dd_pct >= MAX_DRAWDOWN_PCT:
            fail_reasons.append(f"drawdown: {dd_pct:.1f}% >= {MAX_DRAWDOWN_PCT}%")
    elif bets > 0:
        fail_reasons.append("drawdown: no wagered amount")

    # 4. Sharpe
    if sharpe <= MIN_SHARPE:
        fail_reasons.append(f"sharpe: {sharpe:.3f} <= {MIN_SHARPE}")

    passes = len(fail_reasons) == 0
    return ValidationResult(
        strategy_name=name,
        passes=passes,
        status="validated" if passes else "research",
        fail_reasons=fail_reasons,
        metrics={
            "bets": bets,
            "wins": wins,
            "roi": roi,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "wagered": wagered,
            "pnl": pnl,
            "win_rate": (wins / bets * 100) if bets > 0 else 0,
        },
    )


def validate_backtest_results(results: dict) -> List[ValidationResult]:
    """
    Validate all strategies from a backtest results JSON.

    Args:
        results: Dict with "strategies" key mapping name → metrics

    Returns:
        List of ValidationResult for each strategy
    """
    validations = []
    strategies = results.get("strategies", {})

    for name, metrics in strategies.items():
        v = validate_strategy(
            name=name,
            bets=metrics.get("bets", 0),
            wins=metrics.get("wins", 0),
            roi=metrics.get("roi", 0),
            sharpe=metrics.get("sharpe", 0),
            max_drawdown=metrics.get("max_drawdown", 0),
            wagered=metrics.get("wagered", 0),
            pnl=metrics.get("pnl", 0),
        )
        validations.append(v)

    return validations
