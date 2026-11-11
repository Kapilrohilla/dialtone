.PHONY: init up down restart agent agent-dev sip logs ps lk deploy tunnel test test-db server-admin console-dev console-e2e

# The compose file lives in deploy/; .env stays at the repo root.
COMPOSE = docker compose -f deploy/docker-compose.yml --env-file .env

init:            ## create .env and generate LiveKit keys
	scripts/init.sh

up:              ## start redis + livekit + sip + server + console
	$(COMPOSE) up -d --build

down:            ## stop everything (including the agent)
	$(COMPOSE) --profile agent down

restart:
	$(COMPOSE) --profile agent restart

agent:           ## build and start the agent worker container
	$(COMPOSE) --profile agent up -d --build dialtone-agent

agent-dev:       ## run the agent locally in dev mode (needs agent/.venv; reads ../.env)
	cd agent && .venv/bin/python -m livekit.agents start agent.py --dev

test-db:         ## start the disposable Postgres the server tests use (127.0.0.1:55432); no-op if running
	@docker ps --filter name=^dialtone-test-pg$$ --format '{{.Names}}' | grep -q . || \
		docker run -d --rm --name dialtone-test-pg -e POSTGRES_PASSWORD=postgres \
		-p 127.0.0.1:55432:5432 postgres:16.4-alpine
	@until docker exec dialtone-test-pg pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1; do sleep 1; done

test: test-db    ## run unit tests (needs agent/.venv and server/.venv with requirements-dev.txt)
	cd agent && .venv/bin/pytest -q
	cd server && .venv/bin/pytest -q
	cd console && npm ci --prefer-offline && npm test && npm run typecheck && npm run lint
	scripts/tests/test-init.sh
	scripts/tests/test-wait-server.sh
	scripts/tests/test-wait-console.sh
	scripts/tests/test-deploy-rollback.sh

console-dev:     ## run the Next.js console on :3000, proxying /api to the server on :8787
	cd console && DJANGO_URL=http://127.0.0.1:8787 npm run dev

console-e2e:     ## Playwright smoke run of the console against a disposable Django + Postgres (needs make test-db)
	scripts/console-e2e.sh

server-admin:    ## create a server login (Django superuser) in the running container
	$(COMPOSE) exec dialtone-server python manage.py createsuperuser

sip:             ## create the inbound trunk + dispatch rule
	scripts/setup-sip.sh

logs:            ## follow logs, e.g. make logs s=sip  or  make logs s=dialtone-agent
	$(COMPOSE) --profile agent logs -f $(s)

ps:
	$(COMPOSE) --profile agent ps

lk:              ## run the LiveKit CLI, e.g. make lk a="sip inbound list"
	scripts/lk.sh $(a)

# Remote VM (GCP) for `make deploy` / `make tunnel`. GCP_PROJECT has no default: pass it, e.g.
#   make deploy GCP_PROJECT=my-project VM=dialtone GCP_ZONE=asia-south1-c
VM ?= dialtone
GCP_ZONE ?= asia-south1-c
export VM GCP_PROJECT GCP_ZONE

deploy:          ## from your laptop: ship committed code to the VM and restart (ROLLBACK=1 to undo; needs GCP_PROJECT)
	$(if $(GCP_PROJECT),,$(error set GCP_PROJECT, e.g. make deploy GCP_PROJECT=my-project))
	deploy/deploy.sh

tunnel:          ## from your laptop: open the VM console at http://localhost:3000 (server :8787, LiveKit :7880 for Voice test; needs GCP_PROJECT)
	$(if $(GCP_PROJECT),,$(error set GCP_PROJECT, e.g. make tunnel GCP_PROJECT=my-project))
	@echo "Console: http://localhost:3000"
	@echo "Server: http://localhost:8787  (Ctrl-C to close)"
	@echo "LiveKit signalling for the console's Voice test: ws://localhost:7880"
	gcloud compute ssh $(VM) --project $(GCP_PROJECT) --zone $(GCP_ZONE) -- -N -o ExitOnForwardFailure=yes \
		-L 3000:127.0.0.1:3000 -L 8787:127.0.0.1:8787 -L 7880:127.0.0.1:7880
