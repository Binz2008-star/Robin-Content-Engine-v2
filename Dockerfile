FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY src/ ./src/
COPY schema.sql .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Create work directory
RUN mkdir -p /app/work

# Expose port for FastAPI
EXPOSE 8000

# Health check
HEALTHCHECK CMD python -c "from robin_content_engine.database import JobRepository; print('OK')" || exit 1

# Default command
CMD ["uvicorn", "robin_content_engine.api:app", "--host", "0.0.0.0", "--port", "8000"]
