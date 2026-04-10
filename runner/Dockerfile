FROM python:3.12-slim

WORKDIR /app

# Install ADK CLI
RUN pip install google-adk

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY runner/ ./runner/
COPY schema.ddl .

ENV PYTHONPATH=/app

ENTRYPOINT ["python", "-m", "runner.main"]
