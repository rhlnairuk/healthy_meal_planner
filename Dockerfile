FROM python:3.12-slim

WORKDIR /app

# No external dependencies (stdlib only) - just bring the app in.
COPY . /app

# Without this, Python fully buffers stdout when it isn't a TTY, so
# `docker logs` shows nothing until the buffer fills or the process exits.
ENV PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["python3", "webapp.py"]
