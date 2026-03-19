# Contributing to NemoFish

Thanks for your interest in contributing! NemoFish is an R&D project by [ASG Compute](https://asgcompute.com), built on top of [MiroFish](https://github.com/666ghj/MiroFish).

## How to Contribute

### Reporting Issues
- Use [GitHub Issues](https://github.com/ASGCompute/NemoFish/issues) for bugs and feature requests
- Include reproduction steps, expected vs actual behavior, and your environment

### Pull Requests
1. Fork the repo
2. Create a feature branch (`git checkout -b feat/your-feature`)
3. Make your changes
4. Run tests: `cd terminal && python -m pytest tests/`
5. Commit with a descriptive message
6. Open a PR against `main`

### Areas We'd Love Help With
- **New prediction agents** — add specialized agents to the swarm
- **Additional sports** — extend beyond tennis (hockey pipeline exists as a skeleton)
- **Model improvements** — better ELO formulas, alternative ML models
- **Data sources** — integrate new odds providers or stats APIs
- **Dashboard** — new visualizations, better UX

## Development Setup

```bash
cp .env.example .env   # Configure your API keys
npm run setup:all      # Install everything
cd terminal && python -m pytest tests/  # Run tests
```

## Code Style
- Python: Follow PEP 8
- TypeScript/React: Standard ESLint rules
- Commit messages: `feat:`, `fix:`, `docs:`, `test:` prefixes

## License
By contributing, you agree that your contributions will be licensed under GPL-3.0.
