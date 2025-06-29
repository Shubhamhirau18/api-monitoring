import json
import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod

try:
    from prometheus_client import CollectorRegistry, Gauge, Counter, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

from models import MonitoringResult, SLAMetrics, Alert
from config_loader import Config


class DataStorage(ABC):
    """Abstract base class for data storage backends."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    @abstractmethod
    def store_monitoring_result(self, result: MonitoringResult) -> bool:
        """Store a monitoring result."""
        pass
    
    @abstractmethod
    def store_sla_metrics(self, metrics: SLAMetrics) -> bool:
        """Store SLA metrics."""
        pass
    
    @abstractmethod
    def store_alert(self, alert: Alert) -> bool:
        """Store an alert."""
        pass
    
    @abstractmethod
    def get_monitoring_results(self, endpoint_name: str = None, 
                             start_time: datetime = None, 
                             end_time: datetime = None) -> List[MonitoringResult]:
        """Retrieve monitoring results with optional filters."""
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """Test if storage backend is accessible."""
        pass


# InfluxDBStorage class removed - using Prometheus instead


class PrometheusStorage(DataStorage):
    """Prometheus storage backend for direct scraping."""
    
    def __init__(self, config: Config):
        super().__init__(config)
        
        if not PROMETHEUS_AVAILABLE:
            raise ImportError("prometheus-client package required for Prometheus storage")
        
        prom_config = config.data_storage.prometheus
        self.job_name = prom_config.get('job_name', 'api_monitoring')
        
        # Create custom registry for this monitoring instance
        self.registry = CollectorRegistry()
        
        # Define metrics
        self.response_time_gauge = Gauge(
            'api_response_time_milliseconds',
            'API response time in milliseconds',
            ['endpoint_name', 'url', 'status'],
            registry=self.registry
        )
        
        self.request_counter = Counter(
            'api_requests_total',
            'Total API requests',
            ['endpoint_name', 'url', 'status'],
            registry=self.registry
        )
        
        # HTTP Status Code specific metrics
        self.http_requests_total = Counter(
            'api_http_requests_total',
            'Total HTTP requests by status code',
            ['endpoint_name', 'method', 'status_code'],
            registry=self.registry
        )
        
        self.http_requests_2xx = Counter(
            'api_http_requests_2xx_total',
            'Total successful HTTP requests (2xx)',
            ['endpoint_name', 'method'],
            registry=self.registry
        )
        
        self.http_requests_4xx = Counter(
            'api_http_requests_4xx_total', 
            'Total client error HTTP requests (4xx)',
            ['endpoint_name', 'method'],
            registry=self.registry
        )
        
        self.http_requests_5xx = Counter(
            'api_http_requests_5xx_total',
            'Total server error HTTP requests (5xx)',
            ['endpoint_name', 'method'],
            registry=self.registry
        )
        
        # Current status code gauge (for latest status per endpoint)
        self.current_status_code = Gauge(
            'api_current_status_code',
            'Current HTTP status code for endpoint',
            ['endpoint_name', 'method'],
            registry=self.registry
        )
        
        # Outage detection metrics
        self.endpoint_outage_status = Gauge(
            'api_endpoint_outage_status',
            'Endpoint outage status (0=healthy, 1=degraded, 2=outage)',
            ['endpoint_name'],
            registry=self.registry
        )
        
        self.consecutive_failures = Gauge(
            'api_consecutive_failures',
            'Number of consecutive failures for endpoint',
            ['endpoint_name'],
            registry=self.registry
        )
        
        self.outage_duration_seconds = Gauge(
            'api_outage_duration_seconds',
            'Current outage duration in seconds (0 if not in outage)',
            ['endpoint_name'],
            registry=self.registry
        )
        
        self.outage_events_total = Counter(
            'api_outage_events_total',
            'Total outage events',
            ['endpoint_name', 'event_type'],
            registry=self.registry
        )
        
        self.availability_gauge = Gauge(
            'api_availability_percentage',
            'API availability percentage',
            ['endpoint_name'],
            registry=self.registry
        )
        
        self.error_rate_gauge = Gauge(
            'api_error_rate_percentage',
            'API error rate percentage',
            ['endpoint_name'],
            registry=self.registry
        )
        
        # Add system info metric
        self.info_gauge = Gauge(
            'api_monitoring_info',
            'API monitoring system information',
            ['version', 'job'],
            registry=self.registry
        )
        self.info_gauge.labels('1.0.0', self.job_name).set(1)
        
        # Initialize default values for all endpoints from config
        self._initialize_default_metrics()
    
    def _initialize_default_metrics(self):
        """Initialize default metric values for all configured endpoints."""
        try:
            # Initialize metrics for all configured endpoints
            for endpoint in self.config.endpoints:
                endpoint_name = endpoint.name
                
                # Initialize outage metrics with default values
                self.endpoint_outage_status.labels(endpoint_name).set(0)  # 0 = healthy
                self.consecutive_failures.labels(endpoint_name).set(0)
                self.outage_duration_seconds.labels(endpoint_name).set(0)
                self.availability_gauge.labels(endpoint_name).set(100.0)  # Start at 100%
                self.error_rate_gauge.labels(endpoint_name).set(0.0)  # Start at 0%
                
                # Initialize outage event counters (just create the label instances)
                event_types = ['outage_start', 'outage_recovery', 'degradation_start', 'degradation_recovery']
                for event_type in event_types:
                    # Just access the labels to create the metric instances
                    self.outage_events_total.labels(endpoint_name, event_type)
                    
            self.logger.info(f"Initialized default metrics for {len(self.config.endpoints)} endpoints")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize default metrics: {e}")
    
    def store_monitoring_result(self, result: MonitoringResult) -> bool:
        """Store monitoring result as Prometheus metrics."""
        try:
            labels = [result.endpoint_name, result.url, result.status.value]
            
            # Update response time gauge
            if result.response_time_ms is not None:
                self.response_time_gauge.labels(*labels).set(result.response_time_ms)
            
            # Increment request counter
            self.request_counter.labels(*labels).inc()
            
            # HTTP Status Code metrics
            if result.http_status_code is not None:
                # Get HTTP method from metadata
                method = result.metadata.get('method', 'UNKNOWN').upper()
                status_code = str(result.http_status_code)
                
                # Track specific status code
                self.http_requests_total.labels(
                    result.endpoint_name, 
                    method, 
                    status_code
                ).inc()
                
                # Track by status code category
                if 200 <= result.http_status_code < 300:
                    self.http_requests_2xx.labels(result.endpoint_name, method).inc()
                elif 400 <= result.http_status_code < 500:
                    self.http_requests_4xx.labels(result.endpoint_name, method).inc()
                elif 500 <= result.http_status_code < 600:
                    self.http_requests_5xx.labels(result.endpoint_name, method).inc()
                
                # Set current status code for this endpoint
                self.current_status_code.labels(result.endpoint_name, method).set(result.http_status_code)
            
            # Metrics are stored in registry and will be exposed via /metrics endpoint
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store monitoring result in Prometheus: {e}")
            return False
    
    def store_sla_metrics(self, metrics: SLAMetrics) -> bool:
        """Store SLA metrics as Prometheus metrics."""
        try:
            # Update availability gauge
            self.availability_gauge.labels(metrics.endpoint_name).set(metrics.availability_percentage)
            
            # Update error rate gauge
            self.error_rate_gauge.labels(metrics.endpoint_name).set(metrics.error_rate_percentage)
            
            # Metrics are stored in registry and will be exposed via /metrics endpoint
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store SLA metrics in Prometheus: {e}")
            return False
    
    def store_alert(self, alert: Alert) -> bool:
        """Store alert (Prometheus doesn't typically store alerts, this is a no-op)."""
        # Prometheus doesn't store alerts in the same way
        # Alerts are typically handled by Alertmanager
        return True
    
    def get_monitoring_results(self, endpoint_name: str = None, 
                             start_time: datetime = None, 
                             end_time: datetime = None) -> List[MonitoringResult]:
        """Retrieve monitoring results (not supported by Prometheus push gateway)."""
        self.logger.warning("Retrieving historical data not supported by Prometheus push gateway")
        return []
    
    def test_connection(self) -> bool:
        """Test Prometheus metrics functionality."""
        try:
            # Test that we can create and update a metric
            test_gauge = Gauge('test_connection_internal', 'Test connection gauge', registry=self.registry)
            test_gauge.set(1)
            return True
        except Exception:
            return False
    
    def store_outage_state(self, outage_state) -> bool:
        """Store outage state metrics."""
        try:
            from models import OutageStatus
            
            # Map outage status to numeric values for Prometheus
            status_mapping = {
                OutageStatus.HEALTHY: 0,
                OutageStatus.DEGRADED: 1,
                OutageStatus.OUTAGE: 2
            }
            
            endpoint_name = outage_state.endpoint_name
            
            # Update outage status gauge
            self.endpoint_outage_status.labels(endpoint_name).set(
                status_mapping.get(outage_state.status, 0)
            )
            
            # Update consecutive failures
            self.consecutive_failures.labels(endpoint_name).set(outage_state.consecutive_failures)
            
            # Update outage duration
            duration = outage_state.get_outage_duration_seconds() or 0
            self.outage_duration_seconds.labels(endpoint_name).set(duration)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store outage state in Prometheus: {e}")
            return False
    
    def store_outage_event(self, outage_event) -> bool:
        """Store outage event metrics."""
        try:
            # Increment outage event counter
            self.outage_events_total.labels(
                outage_event.endpoint_name,
                outage_event.event_type
            ).inc()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store outage event in Prometheus: {e}")
            return False

    def get_registry(self) -> CollectorRegistry:
        """Get the Prometheus registry for metrics exposure."""
        return self.registry


class FileStorage(DataStorage):
    """File-based storage backend using JSON files."""
    
    def __init__(self, config: Config):
        super().__init__(config)
        
        file_config = config.data_storage.file
        self.base_path = file_config.get('path', './data')
        
        # Create data directory if it doesn't exist
        os.makedirs(self.base_path, exist_ok=True)
        
        self.monitoring_file = os.path.join(self.base_path, 'monitoring_results.jsonl')
        self.sla_file = os.path.join(self.base_path, 'sla_metrics.jsonl')
        self.alerts_file = os.path.join(self.base_path, 'alerts.jsonl')
    
    def store_monitoring_result(self, result: MonitoringResult) -> bool:
        """Store monitoring result to JSON file."""
        try:
            with open(self.monitoring_file, 'a') as f:
                json.dump(result.to_dict(), f)
                f.write('\n')
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store monitoring result to file: {e}")
            return False
    
    def store_sla_metrics(self, metrics: SLAMetrics) -> bool:
        """Store SLA metrics to JSON file."""
        try:
            data = {
                'endpoint_name': metrics.endpoint_name,
                'time_window_start': metrics.time_window_start.isoformat(),
                'time_window_end': metrics.time_window_end.isoformat(),
                'total_requests': metrics.total_requests,
                'successful_requests': metrics.successful_requests,
                'failed_requests': metrics.failed_requests,
                'availability_percentage': metrics.availability_percentage,
                'avg_response_time_ms': metrics.avg_response_time_ms,
                'max_response_time_ms': metrics.max_response_time_ms,
                'min_response_time_ms': metrics.min_response_time_ms,
                'p95_response_time_ms': metrics.p95_response_time_ms,
                'p99_response_time_ms': metrics.p99_response_time_ms,
                'error_rate_percentage': metrics.error_rate_percentage
            }
            
            with open(self.sla_file, 'a') as f:
                json.dump(data, f)
                f.write('\n')
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store SLA metrics to file: {e}")
            return False
    
    def store_alert(self, alert: Alert) -> bool:
        """Store alert to JSON file."""
        try:
            with open(self.alerts_file, 'a') as f:
                json.dump(alert.to_dict(), f)
                f.write('\n')
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store alert to file: {e}")
            return False
    
    def get_monitoring_results(self, endpoint_name: str = None, 
                             start_time: datetime = None, 
                             end_time: datetime = None) -> List[MonitoringResult]:
        """Retrieve monitoring results from JSON file."""
        results = []
        
        try:
            if not os.path.exists(self.monitoring_file):
                return results
            
            with open(self.monitoring_file, 'r') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        
                        # Apply filters
                        if endpoint_name and data.get('endpoint_name') != endpoint_name:
                            continue
                        
                        result_time = datetime.fromisoformat(data['timestamp'])
                        if start_time and result_time < start_time:
                            continue
                        if end_time and result_time > end_time:
                            continue
                        
                        # Convert back to MonitoringResult
                        # This is a simplified version - full implementation would restore all fields
                        results.append(data)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Failed to retrieve monitoring results from file: {e}")
            return []
    
    def test_connection(self) -> bool:
        """Test file storage accessibility."""
        try:
            test_file = os.path.join(self.base_path, 'test.tmp')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            return True
        except Exception:
            return False


class StorageFactory:
    """Factory for creating storage backends."""
    
    @staticmethod
    def create_storage(config: Config) -> DataStorage:
        """Create appropriate storage backend based on configuration."""
        storage_type = config.data_storage.type
        
        if storage_type == 'prometheus':
            return PrometheusStorage(config)
        elif storage_type == 'file':
            return FileStorage(config)
        else:
            raise ValueError(f"Unknown storage type: {storage_type}")


class DataManager:
    """Manages data persistence across multiple storage backends."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        try:
            self.storage = StorageFactory.create_storage(config)
            self.logger.info(f"Initialized {config.data_storage.type} storage backend")
        except Exception as e:
            self.logger.error(f"Failed to initialize storage backend: {e}")
            # Fallback to file storage
            self.storage = FileStorage(config)
            self.logger.info("Falling back to file storage")
    
    def store_monitoring_result(self, result: MonitoringResult) -> bool:
        """Store monitoring result."""
        return self.storage.store_monitoring_result(result)
    
    def store_sla_metrics(self, metrics: SLAMetrics) -> bool:
        """Store SLA metrics."""
        return self.storage.store_sla_metrics(metrics)
    
    def store_alert(self, alert: Alert) -> bool:
        """Store alert."""
        return self.storage.store_alert(alert)
    
    def get_monitoring_results(self, endpoint_name: str = None, 
                             start_time: datetime = None, 
                             end_time: datetime = None) -> List[MonitoringResult]:
        """Retrieve monitoring results."""
        return self.storage.get_monitoring_results(endpoint_name, start_time, end_time)
    
    def test_connection(self) -> bool:
        """Test storage backend connection."""
        return self.storage.test_connection() 