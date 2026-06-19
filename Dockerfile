FROM n8nio/n8n:2.27.0

USER root
RUN mkdir -p /opt/custom-nodes && cd /opt/custom-nodes && npm init -y && npm install pdf-parse
ENV NODE_PATH=/opt/custom-nodes/node_modules
USER node

# Timezone (Railway service variables override these if also set there)
ENV GENERIC_TIMEZONE=America/New_York
ENV TZ=America/New_York

# LP MCP webhook shared secret (S2.1 Calculator Indoctrination "Layer 3" completion ping)
ENV LP_WEBHOOK_SIGNATURE=ef14dba08435f1a7dcf38ac449a4838281fb0e72bb490cb8330c9e7fddddc269

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
