# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Audit fixes**: *Suggest fixes* turns the problems call audits found into ready-to-apply changes, from one
  call (its **Audit** section) or from the last N audited calls of an agent's latest version or workflow
  revision (**Audit fixes** in the agent editor). Repeated problems are grouped and fixes ranked by how often
  they appear × the score they cost; each links to its supporting moments. Workflow fixes (new answers,
  expressions, rewritten step words) reuse `WorkflowSuggestion` with source "audit"; agent fixes (script
  sections, knowledge snippets, settings) are a new `AgentSuggestion`. Both pass the existing checks or are
  dropped. Accepting writes to the draft only; **Versions** shows the fixes each version includes and its
  audit scores against the version before. Optional workspace setting **Auto-apply audit fixes to draft**
  (off by default). `/api/calls/{room}/audit/fixes`, `/api/agents/{id}/audit-fixes`, `/api/audit-fixes/…`;
  daily cap `AUDIT_FIX_DAILY_LIMIT`
  ([KAP-37](https://linear.app/kapil-rohilla/issue/KAP-37/call-audits-suggested-fixes-turn-audit-problems-into-workflow-and)).
- **Call audits**: Gemini scores the AI side of finished calls (naturalness, listening, empathy, pacing,
  flow, accuracy) against weights and instructions set per workspace under Settings → Calls. Scores show
  in Call history and the call slide-over; `GET`/`POST /api/calls/{room}/audit`, and an `audit_sweep`
  management command re-runs audits a restart left stuck
  ([KAP-17](https://linear.app/kapil-rohilla/issue/KAP-17/audit-call-recordings), [#16](https://github.com/Kapilrohilla/dialtone/pull/16)).

## [0.1.0] - 2026-11-11

First open-source release, as **Dialtone** (previously the internal project `ai-calling`)
([KAP-18](https://linear.app/kapil-rohilla/issue/KAP-18/open-source-as-dialtone-remove-carrum-specific-code-restructure-add-a), [#14](https://github.com/Kapilrohilla/ai-calling/pull/14)).

### Added

- Install-wide **project name**, shown in the console's sidebar, sign-in page and tab titles. Defaults to
  "Dialtone"; Django superusers change it in the console under Settings → General (`GET`/`PATCH
  /api/instance/`). `DIALTONE_PROJECT_NAME` sets the starting value.
- OpenAPI schema of the server API at `/api/schema/` (drf-spectacular), committed as `docs/openapi.json`.
- `seed_demo` management command: a demo agent, workflow and knowledge for the fictional Northwind Car
  Rentals, so a fresh install has something to try. Example script and knowledge in
  `examples/car-rental-agent/`.
- `AGENT_COMPANY_NAME`, `AGENT_NAME_PRONUNCIATION` and `AGENT_CONSENT_LINE` worker settings, used when the
  published agent doesn't set its own company, pronunciation or consent line.
- Documentation site (`docs/`, Fumadocs) published to <https://kapilrohilla.github.io/dialtone/>, with a
  generated API reference.
- Community files: Apache-2.0 license, contributing guide, code of conduct, security policy, issue and
  pull request templates.
- GitHub Actions: CI (`scripts/ci-check.sh`), container images on tags
  (`ghcr.io/kapilrohilla/dialtone-agent`, `-server`, `-console`) and docs deployment to GitHub Pages.

### Changed

- Renamed the project to Dialtone. Company and persona names are no longer hard-coded: they come from the
  published agent or the worker's environment.
- Restructured the repository: the Django app moved from `dashboard/` to `server/`; the compose file, VM
  bootstrap, deploy scripts and Terraform moved to `deploy/` (`.env` stays at the repo root; `make`
  targets pass `-f deploy/docker-compose.yml --env-file .env`).
- Compose project is now `dialtone`, and the app services are `dialtone-server`, `dialtone-console`,
  `dialtone-agent` and `dialtone-agent-sim` (previously `dashboard`, `console`, `agent`, `agent-sim`).
- `make deploy` defaults to `VM=dialtone` and the `~/dialtone` checkout, and needs `GCP_PROJECT` (no
  default). The daily retention timer is now `dialtone-purge`.
- `create_member` and `seed_demo` default to the only workspace instead of a hard-coded slug.
- The README is now a short overview; the full documentation moved to the docs site.

### Removed

- Internal tooling and company-specific content that doesn't belong in an open-source project.

### Upgrading from ai-calling

Existing installs keep their data (call history, Redis, recordings) as long as Docker Compose keeps
using the old volume names:

1. Set `COMPOSE_PROJECT_NAME=ai-calling` in the VM's `.env` to keep the existing volumes. `make deploy`
   adds it for you when the old volumes exist.
2. Deploy with `REMOTE_DIR=ai-calling` (the checkout stays in `~/ai-calling`):
   `make deploy GCP_PROJECT=<project> REMOTE_DIR=ai-calling`. The deploy removes the containers with the
   old service names.
3. Once, on the VM: `sudo REMOTE_DIR=ai-calling deploy/bootstrap-server.sh` to replace the old
   `ai-calling-purge` timer with `dialtone-purge`.
4. Run the migrations (the server also runs them when it starts):
   `docker compose -f deploy/docker-compose.yml --env-file .env exec dialtone-server python manage.py migrate`.

[Unreleased]: https://github.com/Kapilrohilla/dialtone/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kapilrohilla/dialtone/releases/tag/v0.1.0
