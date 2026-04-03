# Pin to last stable n8n 1.x — n8n 2.x breaks Code nodes that use $env
# n8n 2.0 forces Task Runners which sandbox Code nodes and block $env access.
# All existing workflows use $env.LP_USERNAME, $env.GHL_API_KEY etc.
# Stay on 1.x until all Code nodes are audited for 2.x sandbox compatibility.
FROM n8nio/n8n:1.123.28

# Install pdf-parse for PDF processing workflows
USER root
WORKDIR /usr/local/lib/node_modules/n8n
RUN npm install pdf-parse

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
