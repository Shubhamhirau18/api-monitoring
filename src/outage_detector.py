import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from models import (
    MonitoringResult, MonitoringStatus, AlertSeverity, 
    OutageStatus, OutageEvent, EndpointOutageState, Alert
)
from config_loader import Config





class OutageDetector:
    """
    Detects API endpoint outages and manages outage state.
    
    Outage Detection Logic:
    - HEALTHY: All recent checks successful
    - DEGRADED: Some failures but not enough for outage
    - OUTAGE: Multiple consecutive failures indicating unavailability
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize outage detection configuration
        self.outage_config = config.monitoring.outage_detection
        
        # Track outage state for each endpoint
        self.endpoint_states: Dict[str, EndpointOutageState] = {}
        self.recent_results: Dict[str, List[MonitoringResult]] = {}
        self.outage_events: List[OutageEvent] = []
        
        self.logger.info(f"Outage detector initialized with config: {self.outage_config}")
    
    def is_result_failure(self, result: MonitoringResult) -> bool:
        """Determine if a monitoring result represents a failure."""
        
        # Check status first
        if result.status in [MonitoringStatus.FAILURE, MonitoringStatus.ERROR]:
            return True
        
        if result.status == MonitoringStatus.TIMEOUT and self.outage_config.timeout_as_failure:
            return True
        
        # Check HTTP status codes
        if result.http_status_code:
            if 500 <= result.http_status_code < 600 and self.outage_config.http_5xx_as_failure:
                return True
            if 400 <= result.http_status_code < 500 and self.outage_config.http_4xx_as_failure:
                return True
        
        return False
    
    def get_failure_reason(self, result: MonitoringResult) -> str:
        """Get the reason for the failure."""
        if result.status == MonitoringStatus.TIMEOUT:
            return "timeout"
        elif result.status in [MonitoringStatus.FAILURE, MonitoringStatus.ERROR]:
            if result.http_status_code:
                if 500 <= result.http_status_code < 600:
                    return "server_error"
                elif 400 <= result.http_status_code < 500:
                    return "client_error"
            return "connection_error"
        else:
            return "unknown"
    
    def update_endpoint_state(self, result: MonitoringResult) -> Optional[OutageEvent]:
        """
        Update the outage state for an endpoint based on the latest monitoring result.
        Returns an OutageEvent if state changes (outage start/recovery).
        """
        endpoint_name = result.endpoint_name
        
        # Initialize state if not exists
        if endpoint_name not in self.endpoint_states:
            self.endpoint_states[endpoint_name] = EndpointOutageState(
                endpoint_name=endpoint_name,
                status=OutageStatus.HEALTHY
            )
        
        # Initialize recent results if not exists
        if endpoint_name not in self.recent_results:
            self.recent_results[endpoint_name] = []
        
        # Add result to recent results and keep only recent ones
        self.recent_results[endpoint_name].append(result)
        cutoff_time = datetime.utcnow() - timedelta(minutes=self.outage_config.failure_window_minutes)
        self.recent_results[endpoint_name] = [
            r for r in self.recent_results[endpoint_name] 
            if r.timestamp >= cutoff_time
        ]
        
        state = self.endpoint_states[endpoint_name]
        current_status = state.status
        is_failure = self.is_result_failure(result)
        
        # Update state based on result
        if is_failure:
            state.consecutive_failures += 1
            state.last_failure_timestamp = result.timestamp
            state.last_error_message = result.error_message or f"HTTP {result.http_status_code}"
            state.last_http_status_code = result.http_status_code
            state.total_failures_in_window = len([r for r in self.recent_results[endpoint_name] if self.is_result_failure(r)])
        else:
            # Success - reset consecutive failures
            consecutive_successes = 1
            for r in reversed(self.recent_results[endpoint_name][:-1]):  # Check previous results
                if not self.is_result_failure(r):
                    consecutive_successes += 1
                else:
                    break
            
            state.last_success_timestamp = result.timestamp
            
            # Reset consecutive failures if we have enough successes for recovery
            if consecutive_successes >= self.outage_config.recovery_success_threshold:
                state.consecutive_failures = 0
        
        # Determine new status
        new_status = self._calculate_outage_status(state)
        outage_event = None
        
        # Check for status changes and generate events
        if current_status != new_status:
            outage_event = self._create_outage_event(state, current_status, new_status, result)
            
            # Update state status
            state.status = new_status
            
            # Set outage start timestamp
            if new_status == OutageStatus.OUTAGE and current_status != OutageStatus.OUTAGE:
                state.outage_start_timestamp = result.timestamp
            elif new_status != OutageStatus.OUTAGE and current_status == OutageStatus.OUTAGE:
                state.outage_start_timestamp = None
        
        return outage_event
    
    def _calculate_outage_status(self, state: EndpointOutageState) -> OutageStatus:
        """Calculate the appropriate outage status based on state."""
        
        if state.consecutive_failures >= self.outage_config.consecutive_failures_threshold:
            return OutageStatus.OUTAGE
        elif state.consecutive_failures >= self.outage_config.degraded_threshold:
            return OutageStatus.DEGRADED
        else:
            return OutageStatus.HEALTHY
    
    def _create_outage_event(self, state: EndpointOutageState, old_status: OutageStatus, 
                           new_status: OutageStatus, result: MonitoringResult) -> OutageEvent:
        """Create an outage event for status changes."""
        
        if new_status == OutageStatus.OUTAGE and old_status != OutageStatus.OUTAGE:
            # Outage started
            severity = AlertSeverity.CRITICAL
            event_type = "outage_start"
            trigger_reason = self.get_failure_reason(result)
        elif old_status == OutageStatus.OUTAGE and new_status != OutageStatus.OUTAGE:
            # Outage recovered
            severity = AlertSeverity.MEDIUM
            event_type = "outage_recovery"
            trigger_reason = "consecutive_successes"
        elif new_status == OutageStatus.DEGRADED and old_status == OutageStatus.HEALTHY:
            # Service degraded
            severity = AlertSeverity.HIGH
            event_type = "degradation_start"
            trigger_reason = self.get_failure_reason(result)
        elif old_status == OutageStatus.DEGRADED and new_status == OutageStatus.HEALTHY:
            # Service recovered from degradation
            severity = AlertSeverity.LOW
            event_type = "degradation_recovery"
            trigger_reason = "consecutive_successes"
        else:
            # Other transitions
            severity = AlertSeverity.MEDIUM
            event_type = f"status_change_{old_status.value}_to_{new_status.value}"
            trigger_reason = "state_transition"
        
        # Calculate outage duration if recovering from outage
        outage_duration_seconds = None
        if event_type == "outage_recovery" and state.outage_start_timestamp:
            outage_duration_seconds = (result.timestamp - state.outage_start_timestamp).total_seconds()
        
        event = OutageEvent(
            endpoint_name=state.endpoint_name,
            event_type=event_type,
            timestamp=result.timestamp,
            severity=severity,
            trigger_reason=trigger_reason,
            consecutive_failures=state.consecutive_failures,
            outage_duration_seconds=outage_duration_seconds,
            metadata={
                'old_status': old_status.value,
                'new_status': new_status.value,
                'http_status_code': result.http_status_code,
                'error_message': result.error_message
            }
        )
        
        self.outage_events.append(event)
        return event
    
    def create_outage_alert(self, outage_event: OutageEvent) -> Alert:
        """Create an alert from an outage event."""
        
        alert_id = f"outage_{outage_event.endpoint_name}_{outage_event.timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        if outage_event.event_type == "outage_start":
            title = f"🚨 OUTAGE: {outage_event.endpoint_name} is DOWN"
            description = (
                f"Endpoint '{outage_event.endpoint_name}' has been detected as DOWN after "
                f"{outage_event.consecutive_failures} consecutive failures. "
                f"Trigger reason: {outage_event.trigger_reason}"
            )
        elif outage_event.event_type == "outage_recovery":
            duration_mins = outage_event.outage_duration_seconds / 60 if outage_event.outage_duration_seconds else 0
            title = f"✅ RECOVERY: {outage_event.endpoint_name} is back online"
            description = (
                f"Endpoint '{outage_event.endpoint_name}' has recovered from outage. "
                f"Outage duration: {duration_mins:.1f} minutes"
            )
        elif outage_event.event_type == "degradation_start":
            title = f"⚠️ DEGRADED: {outage_event.endpoint_name} service degraded"
            description = (
                f"Endpoint '{outage_event.endpoint_name}' is experiencing degraded performance "
                f"with {outage_event.consecutive_failures} consecutive failures."
            )
        elif outage_event.event_type == "degradation_recovery":
            title = f"✅ RECOVERED: {outage_event.endpoint_name} degradation resolved"
            description = f"Endpoint '{outage_event.endpoint_name}' has recovered from degraded state."
        else:
            title = f"📊 STATUS CHANGE: {outage_event.endpoint_name}"
            description = f"Endpoint '{outage_event.endpoint_name}' status changed: {outage_event.event_type}"
        
        return Alert(
            id=alert_id,
            endpoint_name=outage_event.endpoint_name,
            alert_type="outage_detection",
            severity=outage_event.severity,
            timestamp=outage_event.timestamp,
            title=title,
            description=description,
            # Initialize fields needed for recurring alerts
            first_occurrence=outage_event.timestamp,
            last_sent_timestamp=None,  # Will be set when first sent
            repeat_count=0,
            original_title=title,  # Store original title for recurring alerts
            original_description=description,  # Store original description for recurring alerts
            metadata={
                'outage_event': outage_event.to_dict(),
                'consecutive_failures': outage_event.consecutive_failures,
                'trigger_reason': outage_event.trigger_reason
            }
        )
    
    def get_current_outages(self) -> List[EndpointOutageState]:
        """Get list of endpoints currently in outage."""
        return [state for state in self.endpoint_states.values() if state.is_in_outage()]
    
    def get_degraded_endpoints(self) -> List[EndpointOutageState]:
        """Get list of endpoints currently degraded."""
        return [state for state in self.endpoint_states.values() if state.is_degraded()]
    
    def get_endpoint_state(self, endpoint_name: str) -> Optional[EndpointOutageState]:
        """Get the current outage state for a specific endpoint."""
        return self.endpoint_states.get(endpoint_name)
    
    def get_outage_summary(self) -> Dict[str, any]:
        """Get a summary of current outage status."""
        total_endpoints = len(self.endpoint_states)
        outages = self.get_current_outages()
        degraded = self.get_degraded_endpoints()
        healthy = total_endpoints - len(outages) - len(degraded)
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'total_endpoints': total_endpoints,
            'healthy_endpoints': healthy,
            'degraded_endpoints': len(degraded),
            'outage_endpoints': len(outages),
            'current_outages': [state.to_dict() for state in outages],
            'degraded_services': [state.to_dict() for state in degraded],
            'recent_events': [event.to_dict() for event in self.outage_events[-10:]]  # Last 10 events
        }
    
    def check_critical_outages(self) -> List[EndpointOutageState]:
        """Check for outages that have exceeded critical duration."""
        critical_outages = []
        critical_duration = timedelta(minutes=self.outage_config.critical_outage_duration_minutes)
        
        for state in self.get_current_outages():
            if state.outage_start_timestamp:
                outage_duration = datetime.utcnow() - state.outage_start_timestamp
                if outage_duration >= critical_duration:
                    critical_outages.append(state)
        
        return critical_outages 