ARG PYTHON_IMAGE=python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN groupadd --system crm && useradd --system --gid crm --home-dir /app --shell /usr/sbin/nologin crm
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
RUN chmod +x /app/scripts/entrypoint.sh && chown -R crm:crm /app
USER crm
EXPOSE 8080
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
