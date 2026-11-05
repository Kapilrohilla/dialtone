FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 agent
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# agent.py plus knowledge.md (approved pricing/plan rules) when present.
COPY . .

# Last good agent config per number survives restarts here (docker volume agent-cache).
RUN mkdir -p /cache && chown agent:agent /cache

USER agent
# Bake model weights (VAD, turn detector) into the image so calls don't wait on downloads.
RUN python -m livekit.agents download-files

CMD ["python", "-m", "livekit.agents", "start", "agent.py"]
