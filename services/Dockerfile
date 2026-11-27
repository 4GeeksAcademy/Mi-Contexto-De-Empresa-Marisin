FROM python:3.11-slim

WORKDIR /app

RUN python -m pip install --no-cache-dir uv

COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

# La API, el agente y el worker de Celery (misma imagen) no corren como root
# (auditoría OWASP, D17): cuenta de sistema sin home ni shell interactiva.
RUN groupadd --system --gid 10001 trackflow \
    && useradd --system --uid 10001 --gid trackflow --no-create-home --shell /usr/sbin/nologin trackflow

COPY --chown=trackflow:trackflow . .

USER trackflow

EXPOSE 8000

# Modo producción: sin --reload (en desarrollo la API se arranca con uv en el Codespace).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
