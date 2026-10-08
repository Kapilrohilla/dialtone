.PHONY: init up down restart agent agent-dev sip logs ps lk tunnel

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

tunnel:          ## from your laptop: open the VM dashboard at http://localhost:8787
	@echo "Dashboard: http://localhost:8787  (Ctrl-C to close)"
	gcloud compute ssh $(VM) --project $(GCP_PROJECT) --zone $(GCP_ZONE) -- -N -L 8787:127.0.0.1:8787
