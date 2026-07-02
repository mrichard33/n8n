ARG N8N_VERSION=2.27.0

# Stage 1: grab postgresql-client from plain Alpine 3.22
# (n8nio/base strips the apk package manager; we must copy binaries in)
FROM alpine:3.22 AS pg_client
RUN apk add --no-cache postgresql-client

# Stage 2: final image
FROM n8nio/n8n:${N8N_VERSION}

USER root

# Copy psql binary + libpq from the Alpine stage.
# Both images are Alpine 3.22 (same musl/ssl ABI) so no extra libs needed.
COPY --from=pg_client /usr/bin/psql /usr/local/bin/psql
COPY --from=pg_client /usr/lib/libpq.so* /usr/lib/

RUN mkdir -p /opt/custom-nodes && cd /opt/custom-nodes && npm init -y && npm install pdf-parse
COPY scripts/fix-collation.sh /usr/local/bin/fix-collation.sh
RUN chmod +x /usr/local/bin/fix-collation.sh
ENV NODE_PATH=/opt/custom-nodes/node_modules
USER node

# Timezone (Railway service variables override these if also set there)
ENV GENERIC_TIMEZONE=America/New_York
ENV TZ=America/New_York

# LP_WEBHOOK_SIGNATURE: set via Railway env var, never inline
# Railway dashboard → n8n service → Variables → LP_WEBHOOK_SIGNATURE

# MESSAGE_ENGINE_TOKEN: set via Railway env var, never inline
# Consumed by S4.5 v2 (and other agentic) workflows for LP /api/agentic/* auth
# via {{ $env.MESSAGE_ENGINE_TOKEN }}. GHL {{custom_values.*}} tokens do NOT
# resolve inside n8n, so the bearer value must come from the n8n environment.
# Railway dashboard → n8n service → Variables → MESSAGE_ENGINE_TOKEN

ARG PGPASSWORD
ARG PGHOST
ARG PGPORT
ARG PGDATABASE
ARG PGUSER

ENV DB_TYPE=postgresdb
ENV DB_POSTGRESDB_DATABASE=$PGDATABASE
ENV DB_POSTGRESDB_HOST=$PGHOST
ENV DB_POSTGRESDB_PORT=$PGPORT
ENV DB_POSTGRESDB_USER=$PGUSER
ENV DB_POSTGRESDB_PASSWORD=$PGPASSWORD

ARG ENCRYPTION_KEY
ENV N8N_ENCRYPTION_KEY=$ENCRYPTION_KEY

CMD ["n8n start"]
