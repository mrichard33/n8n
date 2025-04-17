# 1. Start from the official n8n image
FROM n8nio/n8n:latest

# 2. Cache‑bust so we can confirm this file is being used
RUN echo "🔧 Using updated Dockerfile"

# 3. Become root to install pdf-parse into n8n’s modules
USER root
WORKDIR /usr/local/lib/node_modules/n8n
RUN npm install pdf-parse

# 4. Revert to the n8n user
USER node

# 5. Expose n8n’s port
EXPOSE 5678

# 6. Launch n8n
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

# 7. Default command
CMD ["n8n", "start"]
