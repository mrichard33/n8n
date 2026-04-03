FROM n8nio/n8n:1.123.28

USER root
RUN mkdir -p /opt/custom-nodes && cd /opt/custom-nodes && npm init -y && npm install pdf-parse
ENV NODE_PATH=/opt/custom-nodes/node_modules

# Disable Task Runners by removing the JsTaskRunnerSandbox
# This forces n8n to fall back to direct Code node execution
RUN find /usr/local/lib/node_modules/n8n -name "JsTaskRunnerSandbox*" -exec rm {} \; 2>/dev/null || true
RUN find /usr/local/lib/node_modules/n8n -name "task-runner*" -type d -exec rm -rf {} \; 2>/dev/null || true

USER node

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
