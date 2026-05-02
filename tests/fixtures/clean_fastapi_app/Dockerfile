# Clean Dockerfile — follows best practices. Hadolint should pass.
FROM python:3.12-slim

RUN useradd -m appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER appuser

HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
