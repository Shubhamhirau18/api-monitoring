# Local Development Setup Guide

## 🚀 Quick Start with Docker

This guide will help you set up the BrightEdge API Monitoring System on any machine using Docker.

### Prerequisites

- **Docker Engine** 20.10+ 
- **Docker Compose** 2.0+
- **Git** (for cloning the repository)
- **4GB+ RAM** (recommended for all services)
- **5GB+ disk space** (for images and data)

## 📋 Installation Steps

### 1. Clone the Repository

```bash
git clone <repository-url>
cd devops_poc
```

### 2. Verify Prerequisites

Check if Docker and Docker Compose are installed:

```bash
# Check Docker version
docker --version
# Should show: Docker version 20.10+ or higher

# Check Docker Compose version
docker-compose version
# Should show: Docker Compose version 2.0+ or higher

# Test Docker is running
docker ps
# Should show running containers (or empty list)
```

### 3. Configuration Setup

The system is pre-configured and ready to run, but you can customize endpoints:

```bash
# Edit monitoring configuration (optional)
nano config/monitoring_config.yaml
```

**Default Configuration Includes:**
- ✅ httpbin.org test endpoints
- ✅ Google health check endpoint
- ✅ Alert configuration (console + email)
- ✅ 30-second monitoring interval
- ✅ 1-minute alert repeat interval

### 4. Build and Start Services

```bash
# Build and start all services
docker-compose up -d

# View logs (optional)
docker-compose logs -f monitoring
```

## 🛠️ Service Architecture

The Docker setup includes 4 services:

| Service | Port | Purpose | Image |
|---------|------|---------|--------|
| **monitoring** | 8080 | Main monitoring app | Custom Alpine (Multi-stage) |
| **prometheus** | 9090 | Metrics storage | prom/prometheus:v2.47.2 |
| **grafana** | 3000 | Visualization | grafana/grafana:10.2.2 |
| **mailhog** | 8025 | Email testing | mailhog/mailhog:v1.0.1 |

## 📊 Access Points

Once services are running, access them via:

### 🖥️ Monitoring Dashboard
```
http://localhost:8080
```
- Real-time endpoint monitoring
- Alert management
- System health overview

### 📈 Prometheus Metrics
```
http://localhost:9090
```
- Raw metrics data
- Query interface
- Service discovery

### 📊 Grafana Dashboards
```
http://localhost:3000
```
- **Username:** admin
- **Password:** admin
- Pre-configured dashboards for API monitoring

### 📧 MailHog (Email Testing)
```
http://localhost:8025
```
- View email alerts sent by the system
- Test email functionality

## 🔧 Development Commands

### Basic Operations

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f [service_name]

# Restart a service
docker-compose restart monitoring

# Rebuild after code changes
docker-compose up -d --build monitoring
```

### Health Checks

```bash
# Check all service health
docker-compose ps

# Test monitoring app configuration
docker-compose exec monitoring python monitor.py --test-config

# Test alert channels
docker-compose exec monitoring python monitor.py --test-alerts
```

### Data Management

```bash
# View data volumes
docker volume ls | grep brightedge

# Backup Prometheus data
docker run --rm -v brightedge-prometheus-data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus-backup.tar.gz -C /data .

# Backup Grafana data
docker run --rm -v brightedge-grafana-data:/data -v $(pwd):/backup alpine tar czf /backup/grafana-backup.tar.gz -C /data .
```

## ⚙️ Configuration Customization

### Adding Your Own Endpoints

Edit `config/monitoring_config.yaml`:

```yaml
endpoints:
  - name: "my_api"
    url: "https://api.mycompany.com/health"
    method: "GET"
    expected_status: 200
    timeout_seconds: 5
    sla:
      availability_percentage: 99.9
      max_response_time_ms: 2000
    slo:
      max_avg_response_time_ms: 1000
      max_error_rate_percentage: 0.5
```

### Alert Configuration

Configure email alerts by editing the MailHog section:

```yaml
alerting:
  enabled: true
  repeat_interval_minutes: 5  # Adjust repeat frequency
  channels:
    - type: "email"
      enabled: true
      smtp_server: "mailhog"
      from_address: "alerts@mycompany.com"
      to_addresses: ["team@mycompany.com"]
```

### Monitoring Intervals

Adjust monitoring frequency:

```yaml
monitoring:
  interval_seconds: 60  # Check every minute instead of 30 seconds
  timeout_seconds: 10
```

## 🐛 Troubleshooting

### Service Won't Start

```bash
# Check service logs
docker-compose logs monitoring

# Common issues:
# 1. Port conflicts - change ports in docker-compose.yml
# 2. Permission issues - check file ownership
# 3. Configuration errors - validate YAML syntax
```

### Port Conflicts

If ports are already in use, modify `docker-compose.yml`:

```yaml
services:
  monitoring:
    ports:
      - "8081:8080"  # Change 8080 to 8081
  
  grafana:
    ports:
      - "3001:3000"  # Change 3000 to 3001
```

### Memory Issues

If running on low-memory systems:

```bash
# Reduce Prometheus retention
# Edit docker-compose.yml:
command:
  - '--storage.tsdb.retention.time=24h'  # Reduce from 200h
```

### SSL/Network Issues

For SSL certificate problems:

```yaml
# In config/monitoring_config.yaml
monitoring:
  verify_ssl: false  # Disable SSL verification for testing
```

## 📦 Image Details

### Multi-Stage Alpine Build

The monitoring application uses a multi-stage Alpine Linux build:

**Stage 1 (Builder):**
- Python 3.13-alpine base
- Build dependencies (gcc, musl-dev, etc.)
- Install Python packages

**Stage 2 (Runtime):**
- Clean Python 3.13-alpine base
- Only runtime dependencies (curl, bash)
- Non-root user for security
- ~50% smaller than slim-based images

### Build Process

```bash
# Manual build (if needed)
docker build -t brightedge-monitoring .

# Check image size
docker images | grep brightedge-monitoring
```

## 🔄 Production Considerations

### Environment Variables

For production, set these environment variables:

```bash
# In docker-compose.yml or .env file
MONITORING_LOG_LEVEL=INFO
MONITORING_CONFIG_PATH=/app/config/monitoring_config.yaml
PROMETHEUS_RETENTION=30d
```

### Resource Limits

Add resource constraints:

```yaml
services:
  monitoring:
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.5'
        reservations:
          memory: 128M
          cpus: '0.25'
```

### Data Persistence

Volumes are automatically created and persisted:
- `brightedge-prometheus-data` - Metrics data
- `brightedge-grafana-data` - Dashboards and settings

## Troublshooting

### Getting Help

1. **Check logs:** `docker-compose logs -f`
2. **Validate config:** `docker-compose exec monitoring python monitor.py --test-config`
3. **Test connectivity:** `docker-compose exec monitoring curl -I http://prometheus:9090`

### Useful Commands

```bash
# Enter monitoring container
docker-compose exec monitoring bash

# Run single monitoring cycle
docker-compose exec monitoring python monitor.py --once

# Check Python packages
docker-compose exec monitoring pip list

# Test specific endpoint
docker-compose exec monitoring python -c "
import requests
print(requests.get('https://httpbin.org/get').status_code)
"
```
---

**The monitoring system should now be running and monitoring your configured endpoints. Visit http://localhost:8080 to see the dashboard!**