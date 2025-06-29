#!/bin/bash

# BrightEdge API Monitoring System - Kind Deployment Script
# This script deploys the monitoring system to a Kind (Kubernetes in Docker) cluster

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Kind is installed
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    if ! command -v kind &> /dev/null; then
        print_error "Kind is not installed. Please install Kind: https://kind.sigs.k8s.io/docs/user/quick-start/"
        exit 1
    fi
    
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl is not installed. Please install kubectl"
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker"
        exit 1
    fi
    
    print_success "Prerequisites check passed"
}

# Create Kind cluster if it doesn't exist
create_kind_cluster() {
    CLUSTER_NAME="brightedge-monitoring"
    
    if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
        print_warning "Kind cluster '${CLUSTER_NAME}' already exists"
        kubectl cluster-info --context kind-${CLUSTER_NAME}
    else
        print_status "Creating Kind cluster '${CLUSTER_NAME}'..."
        
        cat <<EOF | kind create cluster --name ${CLUSTER_NAME} --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
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
        
        print_success "Kind cluster '${CLUSTER_NAME}' created successfully"
    fi
    
    # Set kubectl context
    kubectl config use-context kind-${CLUSTER_NAME}
}

# Build and load Docker images
build_and_load_image() {
    print_status "Building and loading Docker images..."
    
    # Go to project root (assuming script is in k8s/ directory)
    cd "$(dirname "$0")/.."
    
    # Build the monitoring application image
    print_status "Building monitoring application image..."
    docker build -t brightedge-monitoring:latest .
    
    # Pre-pull external images for faster pod startup
    print_status "Pulling external images..."
    docker pull grafana/grafana:12.0.2
    docker pull mailhog/mailhog:v1.0.1
    docker pull prom/prometheus:v2.47.2
    
    # Load all images into Kind cluster
    print_status "Loading images into Kind cluster..."
    kind load docker-image brightedge-monitoring:latest --name brightedge-monitoring
    kind load docker-image grafana/grafana:12.0.2 --name brightedge-monitoring
    kind load docker-image mailhog/mailhog:v1.0.1 --name brightedge-monitoring
    kind load docker-image prom/prometheus:v2.47.2 --name brightedge-monitoring
    
    print_success "All Docker images built and loaded into Kind cluster"
    
    # Return to k8s directory
    cd k8s/
}

# Fix storage class for Kind cluster
fix_storage_class() {
    print_status "Checking and fixing storage class configuration..."
    
    # Get the default storage class in Kind
    DEFAULT_SC=$(kubectl get storageclass -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}')
    
    if [ -z "$DEFAULT_SC" ]; then
        # If no default storage class, get the first available one
        DEFAULT_SC=$(kubectl get storageclass -o jsonpath='{.items[0].metadata.name}')
    fi
    
    if [ -z "$DEFAULT_SC" ]; then
        print_error "No storage class found in cluster"
        exit 1
    fi
    
    print_status "Using storage class: $DEFAULT_SC"
    
    # Update storage.yaml with the correct storage class
    if [ "$DEFAULT_SC" != "standard" ]; then
        print_status "Updating storage class from 'standard' to '$DEFAULT_SC' in storage.yaml"
        sed -i.bak "s/storageClassName: standard/storageClassName: $DEFAULT_SC/g" storage.yaml
        print_success "Storage class updated successfully"
    else
        print_status "Storage class 'standard' is already correct"
    fi
}

# Deploy Kubernetes manifests
deploy_manifests() {
    print_status "Deploying Kubernetes manifests..."
    
    # Deploy in order
    kubectl apply -f namespace.yaml
    kubectl apply -f rbac.yaml
    kubectl apply -f configmaps.yaml
    kubectl apply -f grafana-configmaps.yaml
    
    # Fix storage class for Kind cluster
    fix_storage_class
    kubectl apply -f storage.yaml
    
    # Deploy applications (PVCs will be bound when pods are created due to WaitForFirstConsumer)
    print_status "Deploying applications..."
    kubectl apply -f prometheus-deployment.yaml
    kubectl apply -f grafana-deployment.yaml
    kubectl apply -f mailhog-deployment.yaml
    kubectl apply -f monitoring-app-deployment.yaml
    
    # Wait a moment for PVCs to be bound by the pods
    print_status "Waiting for PersistentVolumeClaims to be bound by pods..."
    sleep 10
    
    # Check PVC status (don't fail if they're still pending due to WaitForFirstConsumer)
    print_status "Current PVC status:"
    kubectl get pvc -n monitoring-system || true
    
    # For WaitForFirstConsumer storage classes, PVCs will be bound when pods start
    print_status "Note: PVCs with 'WaitForFirstConsumer' binding mode will be bound when pods start"
    
    # Deploy services
    kubectl apply -f services.yaml
    
    # Deploy production resources
    kubectl apply -f network-policies.yaml
    kubectl apply -f pod-disruption-budgets.yaml
    kubectl apply -f hpa.yaml
    
    print_success "All manifests deployed successfully"
}

# Wait for deployments to be ready
wait_for_deployments() {
    print_status "Waiting for deployments to be ready..."
    
    kubectl wait --for=condition=available --timeout=300s deployment/prometheus -n monitoring-system
    kubectl wait --for=condition=available --timeout=300s deployment/grafana -n monitoring-system
    kubectl wait --for=condition=available --timeout=300s deployment/mailhog -n monitoring-system
    kubectl wait --for=condition=available --timeout=300s deployment/monitoring-app -n monitoring-system
    
    print_success "All deployments are ready"
    
    # Final check of PVC status
    print_status "Final PVC status check:"
    kubectl get pvc -n monitoring-system
    
    # Check if any PVCs are still pending
    PENDING_PVCS=$(kubectl get pvc -n monitoring-system -o jsonpath='{.items[?(@.status.phase=="Pending")].metadata.name}')
    if [ -n "$PENDING_PVCS" ]; then
        print_warning "Some PVCs are still pending: $PENDING_PVCS"
        print_status "This might be normal for WaitForFirstConsumer storage classes"
    else
        print_success "All PVCs are bound successfully"
    fi
}

# Verify direct access is working
verify_access() {
    print_status "Verifying direct access to services (no port-forwarding needed)..."
    
    # Wait a moment for services to be fully ready
    sleep 10
    
    # Test each service
    local services_ready=true
    
    print_status "Testing monitoring app..."
    if curl -s --connect-timeout 5 http://localhost:8080 > /dev/null 2>&1; then
        print_success "✅ Monitoring app accessible at http://localhost:8080"
    else
        print_warning "⚠️  Monitoring app not yet ready at http://localhost:8080"
        services_ready=false
    fi
    
    print_status "Testing Grafana..."
    if curl -s --connect-timeout 5 http://localhost:3000 > /dev/null 2>&1; then
        print_success "✅ Grafana accessible at http://localhost:3000"
    else
        print_warning "⚠️  Grafana not yet ready at http://localhost:3000"
        services_ready=false
    fi
    
    print_status "Testing Prometheus..."
    if curl -s --connect-timeout 5 http://localhost:9090 > /dev/null 2>&1; then
        print_success "✅ Prometheus accessible at http://localhost:9090"
    else
        print_warning "⚠️  Prometheus not yet ready at http://localhost:9090"
        services_ready=false
    fi
    
    print_status "Testing MailHog..."
    if curl -s --connect-timeout 5 http://localhost:8025 > /dev/null 2>&1; then
        print_success "✅ MailHog accessible at http://localhost:8025"
    else
        print_warning "⚠️  MailHog not yet ready at http://localhost:8025"
        services_ready=false
    fi
    
    if [ "$services_ready" = true ]; then
        print_success "🎉 All services are accessible via direct URLs!"
    else
        print_warning "Some services are still starting up. Please wait a few minutes and try accessing them."
    fi
}

# Display access information
display_access_info() {
    print_success "🚀 BrightEdge API Monitoring System deployed successfully!"
    echo
    echo "📊 Access your services directly (no port-forwarding needed):"
    echo "  • Monitoring Dashboard: http://localhost:8080"
    echo "  • Prometheus:           http://localhost:9090"
    echo "  • Grafana:              http://localhost:3000 (admin/admin)"
    echo "  • MailHog:              http://localhost:8025"
    echo
    echo "🔧 How it works:"
    echo "  • Kind cluster configured with port mappings"
    echo "  • NodePort services with specific port assignments"
    echo "  • Network policies allow external access"
    echo "  • Direct traffic flow: localhost → Kind node → Pod"
    echo
    echo "🛠️  Useful commands:"
    echo "  • View pods:            kubectl get pods -n monitoring-system"
    echo "  • View services:        kubectl get svc -n monitoring-system"
    echo "  • View logs:            kubectl logs -f deployment/monitoring-app -n monitoring-system"
    echo "  • Check node ports:     kubectl get svc -n monitoring-system | grep NodePort"
    echo "  • Delete cluster:       kind delete cluster --name brightedge-monitoring"
}

# Cleanup function
cleanup() {
    # Restore original storage.yaml if backup exists
    if [ -f "storage.yaml.bak" ]; then
        print_status "Restoring original storage.yaml"
        mv storage.yaml.bak storage.yaml
    fi
}

# Set trap to cleanup on script exit
trap cleanup EXIT

# Main execution
main() {
    echo "🚀 Starting BrightEdge API Monitoring System deployment to Kind..."
    echo
    
    check_prerequisites
    create_kind_cluster
    build_and_load_image
    deploy_manifests
    wait_for_deployments
    verify_access
    display_access_info
    
    print_success "🎉 Deployment complete! Your services are ready for use."
    echo "📱 Open http://localhost:8080 in your browser to access the monitoring dashboard."
}

# Run main function
main "$@" 