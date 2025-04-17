FROM n8nio/n8n:latest

# Switch to root to install pdf-parse into n8n’s module folder
USER root
WORKDIR /usr/local/lib/node_modules/n8n
RUN npm install pdf-parse

# Revert to the n8n user
USER node

# Expose the default port
EXPOSE 5678

# Launch n8n
ENTRYPOINT ["n8n"]

# Database connection args
ARG PGPASSWORD
ARG PGHOST
ARG PGPORT
ARG PGDATABASE
ARG PGUSER

# Postgres ENV
ENV DB_TYPE=postgresdb
ENV DB_POSTGRESDB_DATABASE=$PGDATABASE
ENV DB_POSTGRESDB_HOST=$PGHOST
ENV DB_POSTGRESDB_PORT=$PGPORT
ENV DB_POSTGRESDB_USER=$PGUSER
ENV DB_POSTGRESDB_PASSWORD=$PGPASSWORD

# Encryption key
ARG ENCRYPTION_KEY
ENV N8N_ENCRYPTION_KEY=$ENCRYPTION_KEY

CMD ["n8n", "start"]
