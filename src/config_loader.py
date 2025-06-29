import yaml
import os
from typing import Dict, List, Any
from dataclasses import dataclass, field
import validators


@dataclass
class EndpointConfig:
    name: str
    url: str
    method: str = "GET"
    expected_status: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    body: Dict[str, Any] = field(default_factory=dict)
    sla: Dict[str, float] = field(default_factory=dict)
    slo: Dict[str, float] = field(default_factory=dict)
    validation: Dict[str, List[Dict]] = field(default_factory=dict)
    timeout_seconds: int = 10

    def __post_init__(self):
        if not validators.url(self.url):
            raise ValueError(f"Invalid URL: {self.url}")
        
        if self.method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            raise ValueError(f"Invalid HTTP method: {self.method}")


@dataclass
class OutageDetectionConfig:
    consecutive_failures_threshold: int = 3
    degraded_threshold: int = 2
    recovery_success_threshold: int = 2
    failure_window_minutes: int = 10
    critical_outage_duration_minutes: int = 5
    timeout_as_failure: bool = True
    http_5xx_as_failure: bool = True
    http_4xx_as_failure: bool = False


@dataclass
class MonitoringConfig:
    interval_seconds: int = 30
    timeout_seconds: int = 10
    max_workers: int = 5
    verify_ssl: bool = True
    outage_detection: OutageDetectionConfig = field(default_factory=OutageDetectionConfig)


@dataclass
class DataStorageConfig:
    type: str = "file"
    prometheus: Dict[str, str] = field(default_factory=dict)
    file: Dict[str, str] = field(default_factory=dict)


@dataclass
class AlertingConfig:
    enabled: bool = True
    channels: List[Dict[str, Any]] = field(default_factory=list)
    repeat_interval_minutes: int = 15  # How often to repeat active alerts
    max_repeats: int = 0  # Maximum number of repeats (0 = unlimited)
    auto_resolve_after_hours: int = 24  # Auto-resolve alerts after this many hours


@dataclass
class ReportingConfig:
    dashboard_port: int = 8080
    metrics_retention_days: int = 30
    report_intervals: List[str] = field(default_factory=lambda: ["1h", "24h", "7d", "30d"])


@dataclass
class Config:
    monitoring: MonitoringConfig
    endpoints: List[EndpointConfig]
    data_storage: DataStorageConfig
    alerting: AlertingConfig
    reporting: ReportingConfig


class ConfigLoader:
    """Loads and validates monitoring configuration from YAML files."""
    
    def __init__(self, config_path: str = "config/monitoring_config.yaml"):
        self.config_path = config_path
        self.config: Config = None
    
    def load_config(self) -> Config:
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        try:
            with open(self.config_path, 'r') as file:
                config_data = yaml.safe_load(file)
            
            self.config = self._parse_config(config_data)
            self._validate_config()
            
            return self.config
            
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML configuration: {e}")
        except Exception as e:
            raise ValueError(f"Configuration parsing error: {e}")
    
    def _parse_config(self, config_data: Dict[str, Any]) -> Config:
        """Parse raw configuration data into structured objects."""
        
        # Parse monitoring configuration
        monitoring_data = config_data.get('monitoring', {})
        
        # Handle nested outage_detection configuration
        outage_detection_data = monitoring_data.pop('outage_detection', {})
        outage_detection = OutageDetectionConfig(**outage_detection_data)
        
        monitoring = MonitoringConfig(outage_detection=outage_detection, **monitoring_data)
        
        # Parse endpoints
        endpoints_data = config_data.get('endpoints', [])
        endpoints = []
        for endpoint_data in endpoints_data:
            endpoint = EndpointConfig(**endpoint_data)
            endpoints.append(endpoint)
        
        # Parse data storage configuration
        storage_data = config_data.get('data_storage', {})
        data_storage = DataStorageConfig(**storage_data)
        
        # Parse alerting configuration
        alerting_data = config_data.get('alerting', {})
        alerting = AlertingConfig(**alerting_data)
        
        # Parse reporting configuration
        reporting_data = config_data.get('reporting', {})
        reporting = ReportingConfig(**reporting_data)
        
        return Config(
            monitoring=monitoring,
            endpoints=endpoints,
            data_storage=data_storage,
            alerting=alerting,
            reporting=reporting
        )
    
    def _validate_config(self):
        """Validate the loaded configuration."""
        if not self.config.endpoints:
            raise ValueError("At least one endpoint must be configured")
        
        if self.config.monitoring.interval_seconds <= 0:
            raise ValueError("Monitoring interval must be positive")
        
        if self.config.monitoring.max_workers <= 0:
            raise ValueError("Max workers must be positive")
        
        # Validate data storage type
        valid_storage_types = ["prometheus", "file"]
        if self.config.data_storage.type not in valid_storage_types:
            raise ValueError(f"Invalid storage type. Must be one of: {valid_storage_types}")
    
    def get_config(self) -> Config:
        """Get the loaded configuration."""
        if self.config is None:
            self.load_config()
        return self.config
    
    def reload_config(self) -> Config:
        """Reload configuration from file."""
        self.config = None
        return self.load_config()


def load_config(config_path: str = "config/monitoring_config.yaml") -> Config:
    """Convenience function to load configuration."""
    loader = ConfigLoader(config_path)
    return loader.load_config() 