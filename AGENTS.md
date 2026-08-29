# Repository Guidelines

## Project Structure & Module Organization

- `src/` contains the pipeline. Core orchestration is in `src/main.py`; providers live in `src/providers/`, and data collectors in `src/collectors/`.
- `tests/` contains the `pytest` suite, with focused files for configuration, providers, extraction, calculations, state, validation, and PDF generation.
- `prompts/ipo_analyst.md` defines the analyst prompt; `templates/report.html` defines PDF presentation.
- `data/processed_ipos.json` stores short-lived processing state. Generated PDFs go to `reports/` and caches to `.cache/` (both are ignored).
- `.github/workflows/daily-ipo.yml` runs tests and the scheduled production pipeline.

## Build, Test, and Development Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m pytest -q
python -m src.main --dry-run
python -m src.main --today 2026-08-28 --dry-run
```

The first commands create the environment and install dependencies. `pytest` runs the full suite; `--dry-run` exercises the pipeline without email or state updates, while `--today` makes date-sensitive checks reproducible. There is no separate build or lint command.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, and readable small functions. Follow `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Keep deterministic parsing, calculations, validation, and state behavior in Python rather than delegating them to the LLM. No formatter or linter is configured, so match surrounding code and keep imports and public interfaces tidy.

## Testing Guidelines

Tests use `pytest` and follow `tests/test_<area>.py` with `test_<behavior>()` names. Prefer deterministic fixtures and `tmp_path` for filesystem state. Add or update tests whenever changing provider mappings, extraction rules, calculations, validation, configuration, or report generation. No coverage threshold is currently enforced.

## Configuration, Security & Data

Copy `.env.example` for local setup, but never commit `.env`, API keys, Gmail app passwords, or generated reports. Use `DRY_RUN=true` while testing live integrations. Treat prospectus/news inputs as untrusted data, preserve evidence/source IDs, and avoid weakening validation gates. Changes to `data/processed_ipos.json` should be intentional because GitHub Actions commits runtime state.

## Commit & Pull Request Guidelines

Recent commits are short, imperative descriptions; use a focused message such as `fix: handle missing IPO price` or `chore: update IPO agent runtime state`. Pull requests should explain the behavior change, list tests run, identify configuration or workflow changes, and call out any external API assumptions. Include a rendered PDF screenshot or sample when changing `templates/report.html` or report layout.
