# PharmaGuard Backend - Production Docker Image
FROM python:3.11-slim

# Install build deps for cyvcf2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy from backend/ (build context = repo root when using backend/Dockerfile on Render)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Expose port
EXPOSE 8000

# Run the API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
