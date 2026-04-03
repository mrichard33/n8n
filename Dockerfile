# Pin to n8n 1.94.1 — BEFORE Task Runners existed (introduced in 1.111)
# 1.123.28 and 2.x both have Task Runners that break Code nodes
# in production webhook execution. 1.94.1 is the last major stable
# release before Task Runners were added.
FROM n8nio/n8n:1.94.1

# Install pdf-parse in an isolated directory
USER root
RUN mkdir -p /opt/custom-nodes && cd /opt/custom-nodes && npm init -y && npm install pdf-parse
ENV NODE_PATH=/opt/custom-nodes/node_modules

# Revert to the n8n user
USER node

# Expose n8n's port
EXPOSE 5678

# Launch n8n
ENTRYPOINT ["n8n"]

# — Postgres ENV args —
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

# — Encryption key —
ARG ENCRYPTION_KEY
ENV N8N_ENCRYPTION_KEY=$ENCRYPTION_KEY

# Default command
CMD ["n8n", "start"]
