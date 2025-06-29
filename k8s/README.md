# BrightEdge API Monitoring System - Kubernetes Deployment

This directory contains production-ready Kubernetes manifests for deploying the BrightEdge API Monitoring System to a Kubernetes cluster, specifically designed for Kind (Kubernetes in Docker) local development.

## 🏗️ Architecture Overview

The Kubernetes deployment includes:

- **Monitoring Application**: Main Python application with Flask dashboard
- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization and dashboards
- **MailHog**: Email testing and SMTP server
- **Production Features**: RBAC, NetworkPolicies, PodDisruptionBudgets, HPA, Security Context

## 📋 Prerequisites

- **Kind**: Kubernetes in Docker ([Installation Guide](https://kind.sigs.k8s.io/docs/user/quick-start/))
- **kubectl**: Kubernetes CLI ([Installation Guide](https://kubernetes.io/docs/tasks/tools/))
- **Docker**: Container runtime ([Installation Guide](https://docs.docker.com/get-docker/))

## 🚀 Quick Start

### 1. Deploy to Kind

```bash
# Run the automated deployment script
./deploy.sh
```

The script will:
1. ✅ Check prerequisites
2. 🏗️ Create Kind cluster with 3 nodes
3. 🔨 Build and load Docker image
4. 🚀 Deploy all Kubernetes manifests
5. ⏳ Wait for services to be ready
6. 🔗 Setup port forwarding
7. 📊 Display access information

### 2. Access Services

Once deployed, you can access:

- **Monitoring Dashboard**: http://localhost:8080
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin123)
- **MailHog**: http://localhost:8025

## 📁 Manifest Files

| File | Description |
|------|-------------|
| `namespace.yaml` | Namespace with ResourceQuota and LimitRange |
| `rbac.yaml` | ServiceAccounts, Roles and ClusterRoles |
| `configmaps.yaml` | Configuration for monitoring app and Prometheus |
| `grafana-configmaps.yaml` | Grafana datasources and dashboard configuration |
| `storage.yaml` | PersistentVolumeClaims for data persistence |
| `monitoring-app-deployment.yaml` | Main monitoring application deployment |
| `prometheus-deployment.yaml` | Prometheus deployment with proper configuration |
| `grafana-deployment.yaml` | Grafana deployment with provisioned dashboards |
| `mailhog-deployment.yaml` | MailHog email testing service |
| `services.yaml` | ClusterIP and LoadBalancer services |
| `network-policies.yaml` | Network isolation and security policies |
| `pod-disruption-budgets.yaml` | High availability configuration |
| `hpa.yaml` | Horizontal Pod Autoscaler for automatic scaling |

## 🔒 Security Features

### SecurityContext
- ✅ Non-root containers
- ✅ ReadOnlyRootFilesystem where possible
- ✅ Dropped capabilities
- ✅ Seccomp profiles

### RBAC
- ✅ Dedicated ServiceAccounts
- ✅ Minimal required permissions
- ✅ Separate roles for each component

### NetworkPolicies
- ✅ Ingress/Egress traffic control
- ✅ Service-to-service communication
- ✅ DNS resolution allowed
- ✅ External API access for monitoring

## 📊 Production Features

### High Availability
- ✅ Multiple replicas for monitoring app
- ✅ PodDisruptionBudgets prevent service interruption
- ✅ Pod anti-affinity for distribution across nodes

### Auto-scaling
- ✅ HorizontalPodAutoscaler (2-10 replicas)
- ✅ CPU and memory-based scaling
- ✅ Custom scaling policies

### Monitoring & Observability
- ✅ Prometheus metrics collection
- ✅ Grafana dashboards
- ✅ Health checks and probes
- ✅ Resource limits and requests

### Resource Management
- ✅ Namespace-level ResourceQuota
- ✅ Default resource limits
- ✅ Persistent storage for data

## 🛠️ Manual Deployment

If you prefer manual deployment:

```bash
# 1. Create Kind cluster
kind create cluster --name brightedge-monitoring

# 2. Build and load image
docker build -t brightedge-monitoring:latest ..
kind load docker-image brightedge-monitoring:latest --name brightedge-monitoring

# 3. Deploy manifests in order
kubectl apply -f namespace.yaml
kubectl apply -f rbac.yaml
kubectl apply -f configmaps.yaml
kubectl apply -f grafana-configmaps.yaml
kubectl apply -f storage.yaml
kubectl apply -f prometheus-deployment.yaml
kubectl apply -f grafana-deployment.yaml
kubectl apply -f mailhog-deployment.yaml
kubectl apply -f monitoring-app-deployment.yaml
kubectl apply -f services.yaml
kubectl apply -f network-policies.yaml
kubectl apply -f pod-disruption-budgets.yaml
kubectl apply -f hpa.yaml

# 4. Port forward for access
kubectl port-forward -n monitoring-system svc/monitoring-service-lb 8080:8080 &
kubectl port-forward -n monitoring-system svc/prometheus-service-lb 9090:9090 &
kubectl port-forward -n monitoring-system svc/grafana-service-lb 3000:3000 &
kubectl port-forward -n monitoring-system svc/mailhog-service-lb 8025:8025 &
```

## 🔧 Troubleshooting

### Storage Issues
If you encounter PVC binding timeouts:
```bash

# Check storage classes
kubectl get storageclass

# Check PVC status
kubectl get pvc -n monitoring-system
kubectl describe pvc prometheus-data -n monitoring-system
```

### Check Pod Status
```bash
kubectl get pods -n monitoring-system
kubectl describe pod <pod-name> -n monitoring-system
```

### View Logs
```bash
kubectl logs -f deployment/monitoring-app -n monitoring-system
kubectl logs -f deployment/prometheus -n monitoring-system
kubectl logs -f deployment/grafana -n monitoring-system
```

### Check Services
```bash
kubectl get svc -n monitoring-system
kubectl get endpoints -n monitoring-system
```

### Check HPA Status
```bash
kubectl get hpa -n monitoring-system
kubectl describe hpa monitoring-app-hpa -n monitoring-system
```

### Check NetworkPolicies
```bash
kubectl get networkpolicy -n monitoring-system
kubectl describe networkpolicy monitoring-app-network-policy -n monitoring-system
```

## 🧹 Cleanup

### Stop Port Forwarding
```bash
pkill -f "kubectl.*port-forward"
```

### Delete Cluster
```bash
kind delete cluster --name brightedge-monitoring
```

### Delete Resources Only
```bash
kubectl delete namespace monitoring-system
```

## ⚙️ Configuration

### Monitoring Configuration
Edit `configmaps.yaml` to modify:
- Monitoring endpoints
- SLA/SLO thresholds
- Alert settings
- Storage configuration

### Prometheus Configuration
Edit `configmaps.yaml` (prometheus.yml section) to modify:
- Scrape intervals
- Retention policies
- External labels

### Grafana Configuration
- Default credentials: admin/admin123
- Dashboards are auto-provisioned
- Datasources are auto-configured

### Resource Limits
Edit deployment files to adjust:
- CPU/Memory requests and limits
- Replica counts
- Storage sizes

## 🔄 Scaling

### Manual Scaling
```bash
kubectl scale deployment monitoring-app --replicas=5 -n monitoring-system
```

### HPA Configuration
The HorizontalPodAutoscaler automatically scales based on:
- CPU utilization: 70%
- Memory utilization: 80%
- Min replicas: 2
- Max replicas: 10

## 📈 Monitoring

### View Metrics
- Prometheus: http://localhost:9090/graph
- Custom metrics endpoint: http://localhost:8080/metrics

### Grafana Dashboards
- API Monitoring Dashboard (auto-provisioned)
- Response times, success rates, request counts
- Active alerts visualization

### Email Alerts
- View in MailHog: http://localhost:8025
- SMTP server: mailhog-service:1025
- All alerts are automatically sent to configured recipients

## 🎯 Production Considerations

### For Real Production Deployment:

1. **Image Registry**: Push images to a proper registry
2. **Ingress**: Use proper Ingress controller instead of port-forwarding
3. **TLS**: Configure TLS certificates for HTTPS
4. **Storage**: Use production-grade storage classes
5. **Monitoring**: Add cluster-level monitoring (kube-state-metrics, node-exporter)
6. **Backup**: Implement backup strategies for Prometheus/Grafana data
7. **Secrets**: Use proper secret management (HashiCorp Vault, AWS Secrets Manager)
8. **Multi-environment**: Separate dev/staging/prod configurations

---

## Troubleshooting

For issues with the Kubernetes deployment:

1. Check logs: `kubectl logs -f deployment/monitoring-app -n monitoring-system`
2. Verify resources: `kubectl get all -n monitoring-system`
3. Check events: `kubectl get events -n monitoring-system --sort-by='.lastTimestamp'`

---