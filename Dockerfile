FROM python:3.11-slim-bookworm

# Microsoft ODBC Driver 17 + libgomp (required by XGBoost/LightGBM on Linux)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 apt-transport-https unixodbc-dev libgomp1 && \
    curl https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg && \
    curl https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /logs /models

ENV LOG_DIR=/logs
ENV MODELS_DIR=/models

# Default: run the listener daemon.
# Override command in docker-compose for train / dashboard.
CMD ["python", "listener.py"]
