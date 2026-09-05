FROM python:3.13-slim

WORKDIR /app

# copy the application (offline-safe: no pip network at build time)
COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/ /app/backend/
COPY generators/ /app/generators/
COPY database/ /app/database/
COPY supabase/ /app/supabase/

WORKDIR /app/backend

# install what's available; psycopg is optional (CSV dev repo works without)
RUN pip install --no-cache-dir fastapi uvicorn pydantic httpx || true

ENV REVENUEGUARD_ROLLOUT_LEVEL=3 \
    REVENUEGUARD_LLM_PROVIDER=simulated \
    PYTHONUNBUFFERED=1

EXPOSE 8010

# never run as root
USER nobody

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
