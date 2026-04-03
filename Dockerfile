# 1. Start from the official n8n image
FROM n8nio/n8n:latest

# 2. Cache-bust so we can confirm this file is being used
RUN echo "n8n 2.x — pdf-parse installed via isolated directory"

# 3. Become root to install pdf-parse
# n8n 2.x uses catalog: protocol in its package.json which breaks
# npm install inside the n8n modules directory. Instead, install
# pdf-parse in a separate directory and set NODE_PATH so n8n can find it.
USER root
RUN mkdir -p /opt/custom-nodes && cd /opt/custom-nodes && npm init -y && npm install pdf-parse

# 4. Add custom node path so n8n can resolve pdf-parse
ENV NODE_PATH=/opt/custom-nodes/node_modules

# 5. Revert to the n8n user
USER node

# 6. Expose n8n's port
EXPOSE 5678

# 7. Launch n8n
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

# — n8n 2.x compatibility —
# Disable Task Runners (sandboxed code execution) to maintain
# compatibility with existing Code nodes that use $env, fetch(), etc.
ENV N8N_RUNNERS_ENABLED=false

# 8. Default command
CMD ["n8n", "start"]
