# NemoFish — Operator Runbook

## Product Architecture

```
NemoFish = 2 products, 1 repo
├── NemoFish Core (research/simulation)
│   ├── Flask backend :5001
│   ├── Vue frontend :5173
│   └── npm run dev
└── Betting Terminal (live execution)
    ├── live_runner.py → swarm → execute
    ├── Dashboard React :5174
    ├── API server :8888
    └── python3 terminal/live_runner.py
```

## Quick Start

```bash
# 1. Data health check
python3 terminal/feeds/data_health.py

# 2. Run tests
cd terminal && python3 -m pytest tests/ -v

# 3. Scan markets (no bets)
python3 terminal/live_runner.py --scan-only

# 4. Smoke test (paper $1)
python3 terminal/live_runner.py --smoke --smoke-match "Player vs Player"

# 5. Full pipeline (paper)
python3 terminal/live_runner.py

# 6. Live canary ($1 real)
python3 terminal/live_runner.py --live

# 7. Dashboard
cd terminal/dashboard && npx vite --port 5174
cd terminal && python3 api/dashboard_server.py  # API on :8888

# 8. NemoFish Core (separate product)
npm run dev  # Flask :5001 + Vue :5173
```

## Execution Classes

| Class | Stake | Daily | Model | Mode | CLI |
|-------|-------|-------|-------|------|-----|
| INFRA_SMOKE | $1 | $1 | No | Paper | `--smoke` |
| PAPER_MODEL | $5 | $20 | Yes | Paper | *(default)* |
| LIVE_CANARY | $1 | $4 | Yes | Live | `--live` |
| LIVE_FULL | $5 | $20 | Yes | Live | `--live --full` |

## Environment Variables (.env)

| Key | Required | Used By |
|-----|----------|---------|
| `LLM_API_KEY` | Yes | Swarm agents |
| `POLYMARKET_API_KEY` | Yes | Market matching + execution |
| `POLYMARKET_WALLET` | For live | CLOB trading |
| `POLYMARKET_PRIVATE_KEY` | For live | EIP-712 signing |
| `API_TENNIS_KEY` | Yes | Fixture feed |
| `SPORTRADAR_API_KEY` | Optional | Rankings |
| `ODDS_API_KEY` | Optional | Real-time odds |

## Morning Pre-Flight Checklist

1. `python3 terminal/feeds/data_health.py` — all sources green/yellow
2. `python3 -m pytest terminal/tests/ -v` — all tests pass
3. `python3 terminal/live_runner.py --scan-only` — fixtures loading, resolver fail-closed working
4. Check dashboard API: `curl http://localhost:8888/api/health`

## Canary Execution Checklist

1. Confirm bankroll in `config.yaml` = $20
2. Run: `python3 terminal/live_runner.py --smoke --scan-only --smoke-match "X vs Y"`
3. Verify H2H market found, prices in (0.01, 0.99)
4. Run: `python3 terminal/live_runner.py --smoke --smoke-match "X vs Y"`
5. Verify paper trade logged in `execution/runs/`
6. Only then: `python3 terminal/live_runner.py --live`

## Incident Handling

| Symptom | Action |
|---------|--------|
| `UNRESOLVED_PLAYER` spike | Check resolver aliases, update `name_resolver.py` |
| API Tennis 500 | Transient — retry in 5min |
| Polymarket 403 | Cloudflare — check User-Agent, retry |
| No fixtures | Off-season or early morning — wait for schedule |
| Dashboard shows no data | Check API server on :8888, check `last_run.json` |
| Bankroll mismatch | Single source of truth: `config.yaml` → `bankroll.initial_usd` |

## Strategy Status

All strategies are currently `research`. None are `live-approved`.
Run `python3 terminal/backtest_historical.py` to validate.
A strategy needs **positive ROI with N>50 bets** to move to `validated`.

## Ports

| Port | Service | Product |
|------|---------|---------|
| 5001 | Flask backend | NemoFish Core |
| 5173 | Vue frontend | NemoFish Core |
| 5174 | React dashboard | Betting Terminal |
| 8888 | Dashboard API | Betting Terminal |
