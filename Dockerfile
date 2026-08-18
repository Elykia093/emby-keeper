FROM python:3.12.14-bookworm AS builder

WORKDIR /src
COPY . .

RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir .

FROM python:3.12.14-slim-bookworm
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src/scripts/docker-entrypoint.sh /entrypoint.sh

ENV TZ="Asia/Shanghai"
ENV EK_IN_DOCKER="1"

WORKDIR /app
RUN chmod +x /entrypoint.sh \
    && touch config.toml
ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["/entrypoint.sh"]
