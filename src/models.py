from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum


class AlertSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MonitoringStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"


class OutageStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OUTAGE = "outage"


@dataclass
class MonitoringResult:
    """Result of a single monitoring check."""
    endpoint_name: str
    url: str
    timestamp: datetime
    status: MonitoringStatus
    http_status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    response_size_bytes: Optional[int] = None
    error_message: Optional[str] = None
    validation_results: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_success(self) -> bool:
        """Check if the monitoring result is successful."""
        return self.status == MonitoringStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'endpoint_name': self.endpoint_name,
            'url': self.url,
            'timestamp': self.timestamp.isoformat(),
            'status': self.status.value,
            'http_status_code': self.http_status_code,
            'response_time_ms': self.response_time_ms,
            'response_size_bytes': self.response_size_bytes,
            'error_message': self.error_message,
            'validation_results': self.validation_results,
            'metadata': self.metadata
        }


@dataclass
class SLAMetrics:
    """SLA (Service Level Agreement) metrics for an endpoint."""
    endpoint_name: str
    time_window_start: datetime
    time_window_end: datetime
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_downtime_ms: float = 0
    availability_percentage: float = 0.0
    avg_response_time_ms: float = 0.0
    max_response_time_ms: float = 0.0
    min_response_time_ms: float = float('inf')
    p95_response_time_ms: float = 0.0
    p99_response_time_ms: float = 0.0
    error_rate_percentage: float = 0.0

    def calculate_availability(self) -> float:
        """Calculate availability percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    def calculate_error_rate(self) -> float:
        """Calculate error rate percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.failed_requests / self.total_requests) * 100

    def update_availability(self):
        """Update availability percentage."""
        self.availability_percentage = self.calculate_availability()

    def update_error_rate(self):
        """Update error rate percentage."""
        self.error_rate_percentage = self.calculate_error_rate()


@dataclass
class SLOViolation:
    """Represents an SLO (Service Level Objective) violation."""
    endpoint_name: str
    violation_type: str  # 'availability', 'response_time', 'error_rate'
    timestamp: datetime
    severity: AlertSeverity
    current_value: float
    threshold_value: float
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'endpoint_name': self.endpoint_name,
            'violation_type': self.violation_type,
            'timestamp': self.timestamp.isoformat(),
            'severity': self.severity.value,
            'current_value': self.current_value,
            'threshold_value': self.threshold_value,
            'description': self.description,
            'metadata': self.metadata
        }


@dataclass
class Alert:
    """Alert notification."""
    id: str
    endpoint_name: str
    alert_type: str
    severity: AlertSeverity
    timestamp: datetime
    title: str
    description: str
    violation: Optional[SLOViolation] = None
    resolved: bool = False
    resolved_timestamp: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Recurring alert tracking
    first_occurrence: Optional[datetime] = None
    last_sent_timestamp: Optional[datetime] = None
    repeat_count: int = 0
    # Original content for recurring alerts
    original_title: Optional[str] = None
    original_description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'endpoint_name': self.endpoint_name,
            'alert_type': self.alert_type,
            'severity': self.severity.value,
            'timestamp': self.timestamp.isoformat(),
            'title': self.title,
            'description': self.description,
            'violation': self.violation.to_dict() if self.violation else None,
            'resolved': self.resolved,
            'resolved_timestamp': self.resolved_timestamp.isoformat() if self.resolved_timestamp else None,
            'resolved_by': self.resolved_by,
            'resolution_reason': self.resolution_reason,
            'metadata': self.metadata,
            'first_occurrence': self.first_occurrence.isoformat() if self.first_occurrence else None,
            'last_sent_timestamp': self.last_sent_timestamp.isoformat() if self.last_sent_timestamp else None,
            'repeat_count': self.repeat_count,
            'original_title': self.original_title,
            'original_description': self.original_description
        }


@dataclass
class HealthStatus:
    """Overall health status of monitored endpoints."""
    timestamp: datetime
    total_endpoints: int
    healthy_endpoints: int
    unhealthy_endpoints: int
    overall_availability: float
    overall_avg_response_time: float
    active_alerts: int
    endpoints_status: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def is_healthy(self) -> bool:
        """Check if overall system is healthy."""
        return self.healthy_endpoints == self.total_endpoints

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'total_endpoints': self.total_endpoints,
            'healthy_endpoints': self.healthy_endpoints,
            'unhealthy_endpoints': self.unhealthy_endpoints,
            'overall_availability': self.overall_availability,
            'overall_avg_response_time': self.overall_avg_response_time,
            'active_alerts': self.active_alerts,
            'is_healthy': self.is_healthy(),
            'endpoints_status': self.endpoints_status
        }


@dataclass
class OutageEvent:
    """Represents an outage event (start or recovery)."""
    endpoint_name: str
    event_type: str  # 'outage_start', 'outage_recovery'
    timestamp: datetime
    severity: AlertSeverity
    trigger_reason: str  # 'consecutive_failures', 'timeout', 'connection_error'
    consecutive_failures: int = 0
    outage_duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'endpoint_name': self.endpoint_name,
            'event_type': self.event_type,
            'timestamp': self.timestamp.isoformat(),
            'severity': self.severity.value,
            'trigger_reason': self.trigger_reason,
            'consecutive_failures': self.consecutive_failures,
            'outage_duration_seconds': self.outage_duration_seconds,
            'metadata': self.metadata
        }


@dataclass
class EndpointOutageState:
    """Tracks the outage state of an endpoint."""
    endpoint_name: str
    status: OutageStatus
    consecutive_failures: int = 0
    last_success_timestamp: Optional[datetime] = None
    last_failure_timestamp: Optional[datetime] = None
    outage_start_timestamp: Optional[datetime] = None
    total_failures_in_window: int = 0
    last_error_message: Optional[str] = None
    last_http_status_code: Optional[int] = None

    def is_in_outage(self) -> bool:
        """Check if endpoint is currently in outage."""
        return self.status == OutageStatus.OUTAGE

    def is_degraded(self) -> bool:
        """Check if endpoint is degraded."""
        return self.status == OutageStatus.DEGRADED

    def get_outage_duration_seconds(self) -> Optional[float]:
        """Get current outage duration in seconds."""
        if self.outage_start_timestamp and self.is_in_outage():
            return (datetime.utcnow() - self.outage_start_timestamp).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'endpoint_name': self.endpoint_name,
            'status': self.status.value,
            'consecutive_failures': self.consecutive_failures,
            'last_success_timestamp': self.last_success_timestamp.isoformat() if self.last_success_timestamp else None,
            'last_failure_timestamp': self.last_failure_timestamp.isoformat() if self.last_failure_timestamp else None,
            'outage_start_timestamp': self.outage_start_timestamp.isoformat() if self.outage_start_timestamp else None,
            'total_failures_in_window': self.total_failures_in_window,
            'last_error_message': self.last_error_message,
            'last_http_status_code': self.last_http_status_code,
            'is_in_outage': self.is_in_outage(),
            'is_degraded': self.is_degraded(),
            'outage_duration_seconds': self.get_outage_duration_seconds()
        } 