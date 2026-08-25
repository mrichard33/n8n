# lf-report-render — ReportLab render service for the Lightfire weekly report.
# poppler-utils ships in the image for the visual-regression tooling and for
# rasterising a suspect PDF during an incident; the service itself only writes.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects PORT; default matches the healthcheck.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
