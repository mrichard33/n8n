FROM n8nio/n8n:2.27.0

USER root
RUN apk add --no-cache postgresql-client
RUN mkdir -p /opt/custom-nodes && cd /opt/custom-nodes && npm init -y && npm install pdf-parse
COPY scripts/fix-collation.sh /usr/local/bin/fix-collation.sh
RUN chmod +x /usr/local/bin/fix-collation.sh
ENV NODE_PATH=/opt/custom-nodes/node_modules
USER node

# Timezone (Railway service variables override these if also set there)
ENV GENERIC_TIMEZONE=America/New_York
ENV TZ=America/New_York

# LP_WEBHOOK_SIGNATURE removed — set via Railway env var, never inline
# Railway dashboard → n8n service → Variables → LP_WEBHOOK_SIGNATURE

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
