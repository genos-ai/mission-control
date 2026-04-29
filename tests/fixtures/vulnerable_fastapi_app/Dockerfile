# Deliberately insecure Dockerfile for Hadolint testing.
# Missing: USER directive (runs as root), no HEALTHCHECK.
FROM python:3.12
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
