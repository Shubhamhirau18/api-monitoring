# Kind Cluster Development Setup Guide

## 🚀 Local Kubernetes Development with Kind

This guide will help you set up the BrightEdge API Monitoring System on a local Kubernetes cluster using Kind (Kubernetes in Docker). This provides a production-like environment for development and testing.

### Prerequisites

- **Docker Engine** 20.10+
- **Kind** 0.20+ (Kubernetes in Docker)
- **kubectl** 1.28+
- **Git** (for cloning the repository)
- **8GB+ RAM** (recommended for Kind cluster)
- **10GB+ disk space** (for images and cluster data)

## 📋 Installation Steps

### 1. Install Prerequisites

#### Install Kind
```bash
# On macOS
brew install kind

# On Linux
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# On Windows (using Chocolatey)
choco install kind
```

#### Install kubectl
```bash
# On macOS
brew install kubectl

# On Linux
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# On Windows (using Chocolatey)
choco install kubernetes-cli
```

#### Verify Installation
```bash
# Check Kind version
kind --version
# Should show: kind version 0.20.0 or higher

# Check kubectl version
kubectl version --client
# Should show client version

# Check Docker is running
docker ps
# Should show running containers (or empty list)
```

### 2. Clone Repository and Setup

```bash
git clone <repository-url>
cd devops_poc
```

### 3. Deploy to Kind Cluster

#### Automated Deployment (Recommended)
```bash
# Make deploy script executable
chmod +x k8s/deploy.sh

# Run the deployment script
./k8s/deploy.sh
```

The script will automatically:
1. ✅ Check prerequisites
2. ✅ Create Kind cluster with port mappings
3. ✅ Build and load Docker images
4. ✅ Deploy all Kubernetes manifests
5. ✅ Wait for services to be ready
6. ✅ Test connectivity to all services

#### Manual Deployment (Step by Step)
If you prefer to understand each step:

```bash
# 1. Create Kind cluster
cd k8s/
kind create cluster --name brightedge-monitoring --config=- <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
    protocol: TCP
  - containerPort: 30090
    hostPort: 9090
    protocol: TCP
  - containerPort: 30300
    hostPort: 3000
    protocol: TCP
  - containerPort: 30825
    hostPort: 8025
    protocol: TCP
- role: worker
- role: worker
EOF

# 2. Build and load images
cd ..
docker build -t brightedge-monitoring:latest .
docker pull grafana/grafana:12.0.2
docker pull mailhog/mailhog:v1.0.1
docker pull prom/prometheus:v2.47.2

kind load docker-image brightedge-monitoring:latest --name brightedge-monitoring
kind load docker-image grafana/grafana:12.0.2 --name brightedge-monitoring
kind load docker-image mailhog/mailhog:v1.0.1 --name brightedge-monitoring
kind load docker-image prom/prometheus:v2.47.2 --name brightedge-monitoring

# 3. Deploy manifests
cd k8s/
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

# 4. Wait for deployments
kubectl wait --for=condition=available --timeout=300s deployment/prometheus -n monitoring-system
kubectl wait --for=condition=available --timeout=300s deployment/grafana -n monitoring-system
kubectl wait --for=condition=available --timeout=300s deployment/mailhog -n monitoring-system
kubectl wait --for=condition=available --timeout=300s deployment/monitoring-app -n monitoring-system
```

## 🛠️ Kind Cluster Architecture

The Kind setup creates a 3-node cluster:

| Node Type | Role | Purpose |
|-----------|------|---------|
| **Control Plane** | Master | API Server, Scheduler, Controller Manager |
| **Worker 1** | Worker | Run application pods |
| **Worker 2** | Worker | Run application pods |

### Service Architecture in Kind

| Service | Replicas | Port Mapping | Internal Service | NodePort |
|---------|----------|--------------|------------------|----------|
| **Monitoring App** | 2 | localhost:8080 → 30080 | monitoring-service:8080 | 30080 |
| **Prometheus** | 1 | localhost:9090 → 30090 | prometheus-service:9090 | 30090 |
| **Grafana** | 1 | localhost:3000 → 30300 | grafana-service:3000 | 30300 |
| **MailHog** | 1 | localhost:8025 → 30825 | mailhog-service:8025 | 30825 |

## 📊 Access Your Services

### 🖥️ Direct Access (No Port-Forward Needed!)
Once deployment is complete, access services directly:

```bash
# Monitoring Dashboard
open http://localhost:8080
# or
curl http://localhost:8080

# Grafana (login: admin/admin)
open http://localhost:3000

# Prometheus
open http://localhost:9090

# MailHog
open http://localhost:8025
```

### 🔍 How Direct Access Works
1. **Kind Port Mappings**: Host ports forward to cluster NodePorts
2. **NodePort Services**: Services expose specific NodePorts (30080, 30090, etc.)
3. **Network Policies**: Allow external traffic to reach pods
4. **Traffic Flow**: `localhost:8080` → `Kind Node:30080` → `Pod:8080`

## 🔧 Development Commands

### Cluster Management
```bash
# View cluster info
kubectl cluster-info --context kind-brightedge-monitoring

# List all clusters
kind get clusters

# Delete cluster
kind delete cluster --name brightedge-monitoring

# Load new image after rebuild
docker build -t brightedge-monitoring:latest .
kind load docker-image brightedge-monitoring:latest --name brightedge-monitoring
kubectl rollout restart deployment/monitoring-app -n monitoring-system
```

### Pod and Service Management
```bash
# View all resources
kubectl get all -n monitoring-system

# Check pod status
kubectl get pods -n monitoring-system -o wide

# View pod logs
kubectl logs -f deployment/monitoring-app -n monitoring-system

# Execute into pod
kubectl exec -it deployment/monitoring-app -n monitoring-system -- bash

# Check services and endpoints
kubectl get svc -n monitoring-system
kubectl get endpoints -n monitoring-system
```

### Networking and Storage
```bash
# Check network policies
kubectl get networkpolicy -n monitoring-system
kubectl describe networkpolicy monitoring-app-network-policy -n monitoring-system

# Check persistent volumes
kubectl get pv
kubectl get pvc -n monitoring-system

# Check ingress (if any)
kubectl get ingress -n monitoring-system
```

### Scaling and Updates
```bash
# Scale monitoring app
kubectl scale deployment/monitoring-app --replicas=3 -n monitoring-system

# Update image
kubectl set image deployment/monitoring-app monitoring-app=brightedge-monitoring:v2.0.0 -n monitoring-system

# Check rollout status
kubectl rollout status deployment/monitoring-app -n monitoring-system

# Rollback if needed
kubectl rollout undo deployment/monitoring-app -n monitoring-system
```

## ⚙️ Configuration Customization

### Modify Monitoring Endpoints
Edit the monitoring configuration:
```bash
# Edit configmap directly
kubectl edit configmap monitoring-config -n monitoring-system

# Or edit the file and reapply
nano k8s/configmaps.yaml
kubectl apply -f k8s/configmaps.yaml
kubectl rollout restart deployment/monitoring-app -n monitoring-system
```

### Update Resource Limits
```bash
# Edit deployment file
nano k8s/monitoring-app-deployment.yaml

# Apply changes
kubectl apply -f k8s/monitoring-app-deployment.yaml
```

### Modify Port Mappings
To change port mappings, you need to recreate the cluster:
```bash
# Delete existing cluster
kind delete cluster --name brightedge-monitoring

# Edit deploy.sh with new port mappings
nano k8s/deploy.sh

# Redeploy
./k8s/deploy.sh
```

## 🐛 Troubleshooting

### Common Issues and Solutions

#### 1. Cluster Creation Issues
```bash
# Check Docker is running
docker ps

# Check Kind version
kind --version

# Clean up and retry
kind delete cluster --name brightedge-monitoring
./k8s/deploy.sh
```

#### 2. Image Loading Issues
```bash
# Verify image exists locally
docker images | grep brightedge-monitoring

# Reload image
kind load docker-image brightedge-monitoring:latest --name brightedge-monitoring

# Check if image is available in cluster
kubectl get pods -n monitoring-system -o jsonpath='{.items[*].status.containerStatuses[*].image}'
```

#### 3. Pod Startup Issues
```bash
# Check pod events
kubectl describe pod -l app.kubernetes.io/name=monitoring-app -n monitoring-system

# Check logs
kubectl logs -l app.kubernetes.io/name=monitoring-app -n monitoring-system

# Common issues:
# - ImagePullBackOff: Run kind load docker-image
# - CrashLoopBackOff: Check application logs
# - Pending: Check resource limits and node capacity
```

#### 4. Network Connectivity Issues
```bash
# Test internal connectivity
kubectl run debug --image=nicolaka/netshoot --rm -it -- bash
# Inside the pod:
nslookup monitoring-service.monitoring-system.svc.cluster.local
curl http://monitoring-service.monitoring-system:8080

# Check network policies
kubectl describe networkpolicy -n monitoring-system

# Test external connectivity
curl -v http://localhost:8080
```

#### 5. Storage Issues
```bash
# Check PVC status
kubectl get pvc -n monitoring-system

# Check if storage class exists
kubectl get storageclass

# Check persistent volume claims
kubectl describe pvc -n monitoring-system
```

#### 6. Service Access Issues
```bash
# Check service endpoints
kubectl get endpoints -n monitoring-system

# Verify NodePort services
kubectl get svc -n monitoring-system -o wide

# Check Kind port mappings
docker port brightedge-monitoring-control-plane
```

### Debug Commands
```bash
# Get cluster information
kubectl cluster-info dump --output-directory=/tmp/cluster-dump

# Check resource usage
kubectl top nodes
kubectl top pods -n monitoring-system

# Describe all resources
kubectl describe all -n monitoring-system

# Check events
kubectl get events -n monitoring-system --sort-by='.lastTimestamp'
```

## 📦 Development Workflow

### Making Code Changes
```bash
# 1. Make changes to source code
nano src/main.py

# 2. Rebuild and reload image
docker build -t brightedge-monitoring:latest .
kind load docker-image brightedge-monitoring:latest --name brightedge-monitoring

# 3. Restart deployment
kubectl rollout restart deployment/monitoring-app -n monitoring-system

# 4. Check logs
kubectl logs -f deployment/monitoring-app -n monitoring-system
```

### Testing Configuration Changes
```bash
# 1. Edit configuration
nano config/monitoring_config.yaml

# 2. Update configmap
kubectl create configmap monitoring-config \
  --from-file=config/monitoring_config.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Restart monitoring app
kubectl rollout restart deployment/monitoring-app -n monitoring-system
```

### Adding New Kubernetes Resources
```bash
# 1. Create new manifest
nano k8s/new-resource.yaml

# 2. Apply the manifest
kubectl apply -f k8s/new-resource.yaml

# 3. Verify deployment
kubectl get <resource-type> -n monitoring-system
```

## 🔄 Production Considerations

### Resource Monitoring
```bash
# Monitor resource usage
watch kubectl top pods -n monitoring-system

# Check HPA status
kubectl get hpa -n monitoring-system

# View resource limits
kubectl describe deployment/monitoring-app -n monitoring-system
```

### Data Persistence
```bash
# Backup Prometheus data
kubectl exec -n monitoring-system deployment/prometheus -- tar czf - /prometheus | gzip > prometheus-backup.tar.gz

# Backup Grafana data
kubectl exec -n monitoring-system deployment/grafana -- tar czf - /var/lib/grafana | gzip > grafana-backup.tar.gz
```

### Performance Tuning
```bash
# Increase resources for better performance
kubectl patch deployment monitoring-app -n monitoring-system -p='
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "monitoring-app",
            "resources": {
              "requests": {
                "cpu": "200m",
                "memory": "256Mi"
              },
              "limits": {
                "cpu": "1000m",
                "memory": "1Gi"
              }
            }
          }
        ]
      }
    }
  }
}'
```

## 📞 Getting Help

### Useful Resources
- **Kind Documentation**: https://kind.sigs.k8s.io/
- **kubectl Cheat Sheet**: https://kubernetes.io/docs/reference/kubectl/cheatsheet/
- **Kubernetes Troubleshooting**: https://kubernetes.io/docs/tasks/debug/

### Debug Information to Collect
```bash
# Cluster info
kubectl cluster-info
kubectl version

# Pod status
kubectl get pods -n monitoring-system -o wide

# Service status
kubectl get svc -n monitoring-system

# Events
kubectl get events -n monitoring-system --sort-by='.lastTimestamp'

# Logs
kubectl logs -l app.kubernetes.io/name=monitoring-app -n monitoring-system --tail=100
```

### Quick Health Check
```bash
# Run this script to check overall health
cat > health-check.sh << 'EOF'
#!/bin/bash
echo "=== Cluster Health Check ==="
echo "Cluster Info:"
kubectl cluster-info --context kind-brightedge-monitoring

echo -e "\nNode Status:"
kubectl get nodes

echo -e "\nPod Status:"
kubectl get pods -n monitoring-system

echo -e "\nService Status:"
kubectl get svc -n monitoring-system

echo -e "\nConnectivity Test:"
curl -s -o /dev/null -w "Monitoring App: %{http_code}\n" http://localhost:8080
curl -s -o /dev/null -w "Grafana: %{http_code}\n" http://localhost:3000
curl -s -o /dev/null -w "Prometheus: %{http_code}\n" http://localhost:9090
curl -s -o /dev/null -w "MailHog: %{http_code}\n" http://localhost:8025
EOF

chmod +x health-check.sh
./health-check.sh
```

---

**🎉 Success!** You now have a fully functional Kubernetes development environment running locally with Kind. Visit http://localhost:8080 to access your monitoring dashboard! 