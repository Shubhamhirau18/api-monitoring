# Multi-stage build with Alpine Linux for smallest image size
FROM python:3.13-alpine AS builder

# Install build dependencies for Python packages
RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    curl-dev

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage - runtime image
FROM python:3.13-alpine

# Install only runtime dependencies
RUN apk add --no-cache \
    curl \
    bash

# Copy Python packages from builder stage
COPY --from=builder /root/.local /home/monitoring/.local

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY monitor.py .

# Create data and logs directories
RUN mkdir -p /app/data /app/logs

# Create non-root user with proper home directory
RUN adduser -D -s /bin/bash monitoring

# Set proper ownership
RUN chown -R monitoring:monitoring /app /home/monitoring

# Switch to non-root user
USER monitoring

# Update PATH to include user-installed packages
ENV PATH=/home/monitoring/.local/bin:$PATH

# Expose dashboard port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python monitor.py --test-config || exit 1

# Default command
CMD ["python", "monitor.py"]