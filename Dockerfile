# 0. Cache‑bust: you should see this in your build logs
RUN echo "🔧 Using updated Dockerfile"

# 1. Start from the official n8n image
FROM n8nio/n8n:latest

# 2. Become root so we can install into n8n’s own modules
USER root

# 3. Switch into n8n’s package directory
WORKDIR /usr/local/lib/node_modules/n8n

# 4. Install pdf-parse locally (no -g)
RUN npm install pdf-parse

# 5. Revert back to the n8n user
USER node

# 6. Expose n8n’s port
EXPOSE 5678

# 7. Launch n8n
ENTRYPOINT ["n8n"]

# — Your Postgres args —
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

CMD ["n8n", "start"]
