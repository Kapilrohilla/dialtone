.PHONY: init up down restart agent agent-dev sip logs ps lk deploy tunnel test dashboard-admin

init:            ## create .env and generate LiveKit keys
	scripts/init.sh

up:              ## start redis + livekit + sip + dashboard
	docker compose up -d --build

down:            ## stop everything (including the agent)
	docker compose --profile agent down

restart:
	docker compose --profile agent restart

agent:           ## build and start the agent worker container
	docker compose --profile agent up -d --build agent

agent-dev:       ## run the agent locally in dev mode (needs agent/.venv; reads ../.env)
	cd agent && .venv/bin/python -m livekit.agents start agent.py --dev

test:            ## run unit tests (needs agent/.venv and dashboard/.venv with requirements-dev.txt)
	cd agent && .venv/bin/pytest -q
	cd dashboard && .venv/bin/pytest -q

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

tunnel:          ## from your laptop: open the VM dashboard at http://localhost:8787
	@echo "Dashboard: http://localhost:8787  (Ctrl-C to close)"
	gcloud compute ssh $(VM) --project $(GCP_PROJECT) --zone $(GCP_ZONE) -- -N -o ExitOnForwardFailure=yes -L 8787:127.0.0.1:8787
