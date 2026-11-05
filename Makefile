.PHONY: init up down restart agent agent-dev sip logs ps lk deploy tunnel test test-db dashboard-admin console-dev console-e2e

init:            ## create .env and generate LiveKit keys
	scripts/init.sh

up:              ## start redis + livekit + sip + dashboard + console
	docker compose up -d --build

down:            ## stop everything (including the agent)
	docker compose --profile agent down

restart:
	docker compose --profile agent restart

agent:           ## build and start the agent worker container
	docker compose --profile agent up -d --build agent

agent-dev:       ## run the agent locally in dev mode (needs agent/.venv; reads ../.env)
	cd agent && .venv/bin/python -m livekit.agents start agent.py --dev

test-db:         ## start the disposable Postgres the dashboard tests use (127.0.0.1:55432); no-op if running
	@docker ps --filter name=^ai-calling-test-pg$$ --format '{{.Names}}' | grep -q . || \
		docker run -d --rm --name ai-calling-test-pg -e POSTGRES_PASSWORD=postgres \
		-p 127.0.0.1:55432:5432 postgres:16.4-alpine
	@until docker exec ai-calling-test-pg pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1; do sleep 1; done

test: test-db    ## run unit tests (needs agent/.venv and dashboard/.venv with requirements-dev.txt)
	cd agent && .venv/bin/pytest -q
	cd dashboard && .venv/bin/pytest -q
	cd console && npm ci --prefer-offline && npm test && npm run typecheck && npm run lint
	scripts/tests/test-init.sh
	scripts/tests/test-wait-dashboard.sh
	scripts/tests/test-wait-console.sh
	scripts/tests/test-deploy-rollback.sh

console-dev:     ## run the Next.js console on :3000, proxying /api to the dashboard on :8787
	cd console && DJANGO_URL=http://127.0.0.1:8787 npm run dev

console-e2e:     ## Playwright smoke run of the console against a disposable Django + Postgres (needs make test-db)
	scripts/console-e2e.sh

dashboard-admin: ## create a dashboard login (Django superuser) in the running container
	docker compose exec dashboard python manage.py createsuperuser

sip:             ## create the inbound trunk + dispatch rule
	scripts/setup-sip.sh

logs:            ## follow logs, e.g. make logs s=sip
	docker compose --profile agent logs -f $(s)

ps:
	docker compose --profile agent ps

lk:              ## run the LiveKit CLI, e.g. make lk a="sip inbound list"
	scripts/lk.sh $(a)

VM ?= ai-calling
GCP_PROJECT ?= carrum-agent-pilot-dev
GCP_ZONE ?= asia-south1-c

deploy:          ## from your laptop: ship committed code to the VM and restart (ROLLBACK=1 to undo)
	scripts/deploy.sh

tunnel:          ## from your laptop: open the VM console at http://localhost:3000 (and the dashboard on :8787)
	@echo "Console: http://localhost:3000"
	@echo "Dashboard: http://localhost:8787  (Ctrl-C to close)"
	gcloud compute ssh $(VM) --project $(GCP_PROJECT) --zone $(GCP_ZONE) -- -N -o ExitOnForwardFailure=yes \
		-L 3000:127.0.0.1:3000 -L 8787:127.0.0.1:8787
