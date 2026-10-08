.PHONY: init up down restart agent agent-dev sip logs ps lk

init:            ## create .env and generate LiveKit keys
	scripts/init.sh

up:              ## start redis + livekit + sip
	docker compose up -d

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
