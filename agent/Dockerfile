FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 agent
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY agent.py .

USER agent
# Bake model weights (VAD, turn detector) into the image so calls don't wait on downloads.
RUN python -m livekit.agents download-files

CMD ["python", "-m", "livekit.agents", "start", "agent.py"]
