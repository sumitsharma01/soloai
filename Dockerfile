FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Microsoft ODBC Driver 18 validates Azure SQL TLS certificates.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unixodbc && \
    curl -fsSLo /tmp/ms.deb https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb && \
    dpkg -i /tmp/ms.deb && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 && \
    rm -rf /var/lib/apt/lists/* /tmp/ms.deb
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 soloai
COPY app ./app
COPY evals ./evals
COPY agents/soloai-support/instructions.md ./agents/soloai-support/instructions.md
COPY agents/soloai-email/instructions.md ./agents/soloai-email/instructions.md
COPY scripts ./scripts
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
