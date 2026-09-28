# ---- Étape 1 : construction des dépendances -------------------------------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Uniquement le runtime. mypy, pytest, ruff et httpx sont dans
# requirements-dev.txt et n'ont aucune raison d'être dans l'image servie :
# ils y ajoutaient 61 Mo et une surface d'attaque inutile.
COPY requirements-prod.txt .
RUN pip install --upgrade pip && pip install -r requirements-prod.txt

# ---- Étape 2 : image finale ------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="KeyRock" \
      org.opencontainers.image.description="Générateur de tokens cryptographiques (CSPRNG)" \
      org.opencontainers.image.vendor="Vextra Agency"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    KEYROCK_API_HOST=0.0.0.0 \
    KEYROCK_API_PORT=8000 \
    KEYROCK_LOG_LEVEL=INFO \
    KEYROCK_TRUSTED_PROXIES=172.20.0.10/32 \
    KEYROCK_MAX_TRACKED_CLIENTS=10000

RUN groupadd --system --gid 10001 keyrock \
    && useradd --system --uid 10001 --gid keyrock --no-create-home keyrock

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY keyrock_core/ ./keyrock_core/
COPY keyrock_cli/ ./keyrock_cli/
COPY keyrock_api/ ./keyrock_api/
COPY keyrock_shell/ ./keyrock_shell/

# pip et setuptools ne servent plus après la construction : les retirer de
# l'image finale retire ~13 Mo et un binaire d'exécution accessible à un
# conteneur. `--no-cache-dir` ne suffit pas, le paquet lui-même est là.
RUN rm -rf /opt/venv/lib/python3.12/site-packages/pip* \
    /opt/venv/lib/python3.12/site-packages/setuptools* \
    /opt/venv/lib/python3.12/site-packages/_distutils_hack \
    /opt/venv/bin/pip* \
    /opt/venv/bin/pip3*

# Aucun secret dans l'image : uniquement des valeurs par défaut publiques.
ENV HOME=/nonexistent
USER keyrock

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# --forwarded-allow-ips est volontairement restreint a l'adresse exacte de
# Traefik (172.20.0.10), fixes dans docker-compose.yml. Un joker ("*") ferait
# confiance a n'importe quel client pour son X-Forwarded-For, ce qui permettrait de
# contourner le rate limiting en changeant simplement d'en-tete ; un sous-reseau
# entier ferait confiance a tous les conteneurs du reseau, y compris un
# conteneur compromis. Seul Traefik reecrit le X-Forwarded-For : lui seul a le
# droit d'etre cru.
CMD ["uvicorn", "keyrock_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "172.20.0.10"]
