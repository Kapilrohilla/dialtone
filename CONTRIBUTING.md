# Contributing to Dialtone

Thanks for your interest in Dialtone! Bug reports, docs fixes and pull requests are all welcome. By taking
part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report security problems privately as
described in [SECURITY.md](SECURITY.md), never in a public issue.

## Before you start

- **Bugs:** open an issue with the bug report template. Include the component, what you ran, what you
  expected and the relevant logs (`make logs s=<service>`), with phone numbers and keys removed.
- **Features and larger changes:** open an issue first so we can agree on the approach before you spend
  time on it.
- **Small fixes** (typos, docs, obvious bugs): just open a pull request.

## Repository layout

| Path | What |
|---|---|
| `agent/` | Python LiveKit Agents worker and text simulator (pytest) |
| `server/` | Django + Django REST Framework server (pytest-django on PostgreSQL) |
| `console/` | Next.js console (Vitest, ESLint, TypeScript, Playwright e2e) |
| `deploy/` | Compose file, VM bootstrap and deploy scripts, optional Terraform |
| `scripts/` | `init.sh`, SIP setup, LiveKit CLI wrapper, `ci-check.sh`, shell script tests |
| `docs/` | Documentation site (Fumadocs, static export to GitHub Pages) |
| `examples/` | Example agents |

## Development setup

You need Python 3.12+, Node 22, Docker and `make`. Running the full stack needs Linux (host networking);
the tests run anywhere Docker does.

```bash
git clone https://github.com/Kapilrohilla/dialtone.git && cd dialtone

# Python virtualenvs used by `make test`
python3 -m venv agent/.venv  && agent/.venv/bin/pip install -r agent/requirements-dev.txt
python3 -m venv server/.venv && server/.venv/bin/pip install -r server/requirements-dev.txt

# Console dependencies
(cd console && npm ci)
```

Run the whole stack (Linux):

```bash
make init        # .env with generated secrets; add GOOGLE_API_KEY (or another pipeline's keys)
make up          # media services, server and console
make agent       # agent worker and simulator
```

Or iterate on one part:

```bash
make agent-dev   # agent in LiveKit dev mode (reads ../.env; point LIVEKIT_URL at a LiveKit server)
make console-dev # console on :3000, proxying /api to the server on :8787
```

The agent needs its model files once: `cd agent && .venv/bin/python -m livekit.agents download-files`.

Every `make` target has a one-line comment in the `Makefile`.

## Running the tests

```bash
make test             # agent + server pytest, console tests/typecheck/lint, shell script tests
scripts/ci-check.sh   # exactly what CI runs: make test, then a production console build
```

- `make test` starts a disposable PostgreSQL for the server tests (`make test-db`: container
  `dialtone-test-pg` on `127.0.0.1:55432`). To use another server, set `TEST_POSTGRES_HOST`,
  `TEST_POSTGRES_PORT`, `TEST_POSTGRES_USER` and `TEST_POSTGRES_PASSWORD`.
- Console end-to-end smoke run: `cd console && npx playwright install chromium` once, then
  `make test-db && make console-e2e`.
- Docs: `cd docs && npm ci && npm run build`.

## Pull requests

- Branch from `main` and keep each PR focused on one change.
- Fill in the pull request template: what changed, why, and how you tested it.
- `scripts/ci-check.sh` must pass; CI runs it on every push and pull request.
- Add or update tests with every behaviour change.
- Update the docs (`docs/content/docs/`) when you change setup, settings or anything users see. New
  environment variables go in `.env.example` with a comment, and in
  `docs/content/docs/getting-started/configuration.mdx`.
- Add a line under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- Server API changes: regenerate `docs/openapi.json` from the server so the API reference stays current.
- Pin versions (Docker images, Python and npm dependencies); never use `latest`.
- Never commit secrets, `.env`, real phone numbers, recordings or call data.
- Commit messages: short imperative summary line (`fix: …`, `feat: …`, `docs: …` prefixes are welcome),
  then a blank line and the why, if it isn't obvious.

Maintainers squash-merge pull requests once CI is green and a review is approved.

## License

Dialtone is licensed under the [Apache License 2.0](LICENSE). By contributing, you agree that your
contributions are licensed under the same license.
