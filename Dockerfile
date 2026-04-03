FROM n8nio/n8n:1.123.28

USER root
RUN mkdir -p /opt/custom-nodes && cd /opt/custom-nodes && npm init -y && npm install pdf-parse
ENV NODE_PATH=/opt/custom-nodes/node_modules

# Patch the Code node to bypass JsTaskRunnerSandbox and use direct execution
# Find the Code.node.js file and replace the sandbox call with direct vm execution
RUN CODE_FILE=$(find /usr/local/lib/node_modules/n8n -path "*/nodes/Code/Code.node.js" | head -1) && \
    if [ -f "$CODE_FILE" ]; then \
      sed -i 's/JsTaskRunnerSandbox/JsCodeSandbox/g' "$CODE_FILE" 2>/dev/null || true; \
    fi

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
