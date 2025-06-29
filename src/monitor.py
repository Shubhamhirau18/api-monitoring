import requests
import time
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics
import logging

from config_loader import Config, EndpointConfig
from models import (
    MonitoringResult, MonitoringStatus, SLAMetrics, SLOViolation, 
    Alert, AlertSeverity, HealthStatus
)


class ContentValidator:
    """Validates HTTP response content based on configuration."""
    
    @staticmethod
    def validate_response(response: requests.Response, validation_config: Dict) -> Dict[str, bool]:
        """Validate response content based on configuration."""
        results = {}
        
        if not validation_config or 'content_checks' not in validation_config:
            return results
        
        try:
            response_json = response.json()
        except (json.JSONDecodeError, ValueError):
            response_json = None
        
        for check in validation_config['content_checks']:
            check_type = check.get('type')
            
            if check_type == 'json_key_exists':
                key = check.get('key')
                results[f'json_key_exists_{key}'] = (
                    response_json is not None and key in response_json
                )
            
            elif check_type == 'json_key_value':
                key = check.get('key')
                expected_value = check.get('expected')
                results[f'json_key_value_{key}'] = (
                    response_json is not None and 
                    response_json.get(key) == expected_value
                )
            
            elif check_type == 'status_code':
                expected_status = check.get('expected')
                results[f'status_code_{expected_status}'] = (
                    response.status_code == expected_status
                )
            
            elif check_type == 'response_time':
                max_time = check.get('max_ms', 5000)
                response_time = getattr(response, 'elapsed', timedelta()).total_seconds() * 1000
                results[f'response_time_under_{max_time}ms'] = response_time <= max_time
        
        return results


class HTTPMonitor:
    """Performs HTTP monitoring checks for endpoints."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        
        # Configure SSL verification
        if not self.config.monitoring.verify_ssl:
            # Disable SSL warnings when verification is disabled
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.logger.warning("SSL verification is disabled - this should only be used for testing!")
        
        # Configure session with retries and timeouts
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=1,
                backoff_factor=0.1,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
    
    def check_endpoint(self, endpoint: EndpointConfig) -> MonitoringResult:
        """Perform monitoring check for a single endpoint."""
        start_time = time.time()
        timestamp = datetime.now()
        
        try:
            # Prepare request parameters
            timeout = getattr(endpoint, 'timeout_seconds', self.config.monitoring.timeout_seconds)
            
            # Handle dynamic values in body (like timestamp)
            body = endpoint.body.copy() if endpoint.body else None
            if body:
                body = self._replace_dynamic_values(body, timestamp)
            
            # Make HTTP request
            response = self.session.request(
                method=endpoint.method,
                url=endpoint.url,
                headers=endpoint.headers,
                json=body if body else None,
                timeout=timeout,
                verify=self.config.monitoring.verify_ssl
            )
            
            end_time = time.time()
            response_time_ms = (end_time - start_time) * 1000
            
            # Determine status
            status = MonitoringStatus.SUCCESS if response.status_code == endpoint.expected_status else MonitoringStatus.FAILURE
            
            # Validate response content
            validation_results = ContentValidator.validate_response(response, endpoint.validation)
            
            # If any validation fails, mark as failure
            if validation_results and not all(validation_results.values()):
                status = MonitoringStatus.FAILURE
            
            return MonitoringResult(
                endpoint_name=endpoint.name,
                url=endpoint.url,
                timestamp=timestamp,
                status=status,
                http_status_code=response.status_code,
                response_time_ms=response_time_ms,
                response_size_bytes=len(response.content),
                validation_results=validation_results,
                metadata={
                    'method': endpoint.method,
                    'expected_status': endpoint.expected_status,
                    'headers_sent': dict(endpoint.headers) if endpoint.headers else {}
                }
            )
        
        except requests.exceptions.Timeout:
            return MonitoringResult(
                endpoint_name=endpoint.name,
                url=endpoint.url,
                timestamp=timestamp,
                status=MonitoringStatus.TIMEOUT,
                error_message="Request timeout",
                response_time_ms=(time.time() - start_time) * 1000,
                metadata={'method': endpoint.method}
            )
        
        except requests.exceptions.RequestException as e:
            return MonitoringResult(
                endpoint_name=endpoint.name,
                url=endpoint.url,
                timestamp=timestamp,
                status=MonitoringStatus.ERROR,
                error_message=str(e),
                response_time_ms=(time.time() - start_time) * 1000,
                metadata={'method': endpoint.method}
            )
        
        except Exception as e:
            self.logger.error(f"Unexpected error monitoring {endpoint.name}: {e}")
            return MonitoringResult(
                endpoint_name=endpoint.name,
                url=endpoint.url,
                timestamp=timestamp,
                status=MonitoringStatus.ERROR,
                error_message=f"Unexpected error: {str(e)}",
                response_time_ms=(time.time() - start_time) * 1000,
                metadata={'method': endpoint.method}
            )
    
    def _replace_dynamic_values(self, data: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
        """Replace dynamic values in request body."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str) and value == "{{timestamp}}":
                result[key] = timestamp.isoformat()
            elif isinstance(value, dict):
                result[key] = self._replace_dynamic_values(value, timestamp)
            else:
                result[key] = value
        return result


class SLACalculator:
    """Calculates SLA metrics and detects SLO violations."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def calculate_sla_metrics(self, endpoint_name: str, results: List[MonitoringResult], 
                             window_start: datetime, window_end: datetime) -> SLAMetrics:
        """Calculate SLA metrics for an endpoint over a time window."""
        
        endpoint_results = [r for r in results if r.endpoint_name == endpoint_name]
        
        if not endpoint_results:
            return SLAMetrics(
                endpoint_name=endpoint_name,
                time_window_start=window_start,
                time_window_end=window_end
            )
        
        # Basic counts
        total_requests = len(endpoint_results)
        successful_requests = sum(1 for r in endpoint_results if r.is_success())
        failed_requests = total_requests - successful_requests
        
        # Response times (only for successful requests)
        response_times = [r.response_time_ms for r in endpoint_results 
                         if r.response_time_ms is not None and r.is_success()]
        
        # Calculate metrics
        metrics = SLAMetrics(
            endpoint_name=endpoint_name,
            time_window_start=window_start,
            time_window_end=window_end,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests
        )
        
        if response_times:
            metrics.avg_response_time_ms = statistics.mean(response_times)
            metrics.max_response_time_ms = max(response_times)
            metrics.min_response_time_ms = min(response_times)
            
            # Calculate percentiles
            sorted_times = sorted(response_times)
            if len(sorted_times) >= 20:  # Only calculate percentiles if we have enough data
                metrics.p95_response_time_ms = sorted_times[int(len(sorted_times) * 0.95)]
                metrics.p99_response_time_ms = sorted_times[int(len(sorted_times) * 0.99)]
        
        metrics.update_availability()
        metrics.update_error_rate()
        
        return metrics
    
    def check_slo_violations(self, endpoint: EndpointConfig, metrics: SLAMetrics) -> List[SLOViolation]:
        """Check for SLO violations based on endpoint configuration and current metrics."""
        violations = []
        timestamp = datetime.now()
        
        slo_config = endpoint.slo
        if not slo_config:
            return violations
        
        # Check availability SLO
        if 'max_error_rate_percentage' in slo_config:
            max_error_rate = slo_config['max_error_rate_percentage']
            if metrics.error_rate_percentage > max_error_rate:
                violations.append(SLOViolation(
                    endpoint_name=endpoint.name,
                    violation_type='error_rate',
                    timestamp=timestamp,
                    severity=self._determine_severity(
                        metrics.error_rate_percentage, max_error_rate, 'error_rate'
                    ),
                    current_value=metrics.error_rate_percentage,
                    threshold_value=max_error_rate,
                    description=f"Error rate {metrics.error_rate_percentage:.2f}% exceeds SLO threshold of {max_error_rate}%"
                ))
        
        # Check response time SLO
        if 'max_avg_response_time_ms' in slo_config:
            max_avg_response_time = slo_config['max_avg_response_time_ms']
            if metrics.avg_response_time_ms > max_avg_response_time:
                violations.append(SLOViolation(
                    endpoint_name=endpoint.name,
                    violation_type='response_time',
                    timestamp=timestamp,
                    severity=self._determine_severity(
                        metrics.avg_response_time_ms, max_avg_response_time, 'response_time'
                    ),
                    current_value=metrics.avg_response_time_ms,
                    threshold_value=max_avg_response_time,
                    description=f"Average response time {metrics.avg_response_time_ms:.2f}ms exceeds SLO threshold of {max_avg_response_time}ms"
                ))
        
        # Check SLA availability
        sla_config = endpoint.sla
        if sla_config and 'availability_percentage' in sla_config:
            min_availability = sla_config['availability_percentage']
            if metrics.availability_percentage < min_availability:
                violations.append(SLOViolation(
                    endpoint_name=endpoint.name,
                    violation_type='availability',
                    timestamp=timestamp,
                    severity=self._determine_severity(
                        metrics.availability_percentage, min_availability, 'availability'
                    ),
                    current_value=metrics.availability_percentage,
                    threshold_value=min_availability,
                    description=f"Availability {metrics.availability_percentage:.2f}% below SLA threshold of {min_availability}%"
                ))
        
        return violations
    
    def _determine_severity(self, current_value: float, threshold_value: float, metric_type: str) -> AlertSeverity:
        """Determine alert severity based on how much the metric deviates from threshold."""
        
        if metric_type == 'availability':
            deviation = threshold_value - current_value  # Lower is worse for availability
        else:
            deviation = current_value - threshold_value  # Higher is worse for response time/error rate
        
        if metric_type == 'availability':
            if deviation >= 5.0:  # 5% below threshold
                return AlertSeverity.CRITICAL
            elif deviation >= 2.0:  # 2% below threshold
                return AlertSeverity.HIGH
            elif deviation >= 1.0:  # 1% below threshold
                return AlertSeverity.MEDIUM
            else:
                return AlertSeverity.LOW
        else:
            # For response time and error rate
            percentage_over = (deviation / threshold_value) * 100
            if percentage_over >= 100:  # 100% over threshold
                return AlertSeverity.CRITICAL
            elif percentage_over >= 50:  # 50% over threshold
                return AlertSeverity.HIGH
            elif percentage_over >= 25:  # 25% over threshold
                return AlertSeverity.MEDIUM
            else:
                return AlertSeverity.LOW


class MonitoringService:
    """Main monitoring service that orchestrates monitoring checks."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.http_monitor = HTTPMonitor(config)
        self.sla_calculator = SLACalculator(config)
        self.results_history: List[MonitoringResult] = []
        
        # Initialize outage detector
        from outage_detector import OutageDetector
        self.outage_detector = OutageDetector(config)
    
    def run_monitoring_cycle(self) -> List[MonitoringResult]:
        """Run a single monitoring cycle for all endpoints."""
        results = []
        outage_events = []
        
        with ThreadPoolExecutor(max_workers=self.config.monitoring.max_workers) as executor:
            # Submit monitoring tasks
            future_to_endpoint = {
                executor.submit(self.http_monitor.check_endpoint, endpoint): endpoint
                for endpoint in self.config.endpoints
            }
            
            # Collect results
            for future in as_completed(future_to_endpoint):
                endpoint = future_to_endpoint[future]
                try:
                    result = future.result()
                    results.append(result)
                    self.logger.info(f"Monitored {endpoint.name}: {result.status.value}")
                except Exception as e:
                    self.logger.error(f"Error monitoring {endpoint.name}: {e}")
                    # Create error result
                    error_result = MonitoringResult(
                        endpoint_name=endpoint.name,
                        url=endpoint.url,
                        timestamp=datetime.now(),
                        status=MonitoringStatus.ERROR,
                        error_message=str(e)
                    )
                    results.append(error_result)
        
        # Process outage detection for each result
        for result in results:
            outage_event = self.outage_detector.update_endpoint_state(result)
            if outage_event:
                outage_events.append(outage_event)
                self.logger.warning(f"Outage event detected: {outage_event.event_type} for {outage_event.endpoint_name}")
        
        # Store results in history
        self.results_history.extend(results)
        
        # Clean up old results (keep only last 24 hours by default)
        cutoff_time = datetime.now() - timedelta(hours=24)
        self.results_history = [r for r in self.results_history if r.timestamp > cutoff_time]
        
        # Store outage events for further processing (alerts, metrics)
        if hasattr(self, '_outage_events'):
            self._outage_events.extend(outage_events)
        else:
            self._outage_events = outage_events
        
        return results
    
    def analyze_sla_compliance(self, window_hours: int = 1) -> Dict[str, SLAMetrics]:
        """Analyze SLA compliance for all endpoints over the specified time window."""
        window_end = datetime.now()
        window_start = window_end - timedelta(hours=window_hours)
        
        sla_metrics = {}
        for endpoint in self.config.endpoints:
            metrics = self.sla_calculator.calculate_sla_metrics(
                endpoint.name, self.results_history, window_start, window_end
            )
            sla_metrics[endpoint.name] = metrics
        
        return sla_metrics
    
    def check_violations(self) -> Dict[str, List[SLOViolation]]:
        """Check for SLO violations for all endpoints."""
        violations = {}
        sla_metrics = self.analyze_sla_compliance(window_hours=1)
        
        for endpoint in self.config.endpoints:
            endpoint_metrics = sla_metrics.get(endpoint.name)
            if endpoint_metrics:
                endpoint_violations = self.sla_calculator.check_slo_violations(endpoint, endpoint_metrics)
                if endpoint_violations:
                    violations[endpoint.name] = endpoint_violations
        
        return violations
    
    def get_health_status(self) -> HealthStatus:
        """Get overall health status of all monitored endpoints."""
        now = datetime.now()
        recent_cutoff = now - timedelta(minutes=5)  # Consider last 5 minutes for health status
        
        endpoint_statuses = {}
        healthy_count = 0
        total_endpoints = len(self.config.endpoints)
        
        total_response_times = []
        total_successful = 0
        total_requests = 0
        
        for endpoint in self.config.endpoints:
            # Get recent results for this endpoint
            recent_results = [
                r for r in self.results_history 
                if r.endpoint_name == endpoint.name and r.timestamp > recent_cutoff
            ]
            
            if recent_results:
                latest_result = max(recent_results, key=lambda x: x.timestamp)
                is_healthy = latest_result.is_success()
                
                # Calculate basic metrics
                successful = sum(1 for r in recent_results if r.is_success())
                total = len(recent_results)
                avg_response_time = statistics.mean([
                    r.response_time_ms for r in recent_results 
                    if r.response_time_ms is not None and r.is_success()
                ]) if any(r.response_time_ms is not None and r.is_success() for r in recent_results) else 0
                
                endpoint_statuses[endpoint.name] = {
                    'healthy': is_healthy,
                    'last_check': latest_result.timestamp,
                    'status': latest_result.status.value,
                    'response_time_ms': latest_result.response_time_ms,
                    'availability_percentage': (successful / total) * 100 if total > 0 else 0,
                    'avg_response_time_ms': avg_response_time,
                    'total_requests': total
                }
                
                if is_healthy:
                    healthy_count += 1
                
                # Aggregate for overall metrics
                total_successful += successful
                total_requests += total
                if avg_response_time > 0:
                    total_response_times.append(avg_response_time)
            else:
                endpoint_statuses[endpoint.name] = {
                    'healthy': False,
                    'last_check': None,
                    'status': 'unknown',
                    'response_time_ms': None,
                    'availability_percentage': 0,
                    'avg_response_time_ms': 0,
                    'total_requests': 0
                }
        
        # Calculate overall metrics
        overall_availability = (total_successful / total_requests * 100) if total_requests > 0 else 0
        overall_avg_response_time = statistics.mean(total_response_times) if total_response_times else 0
        
        return HealthStatus(
            timestamp=now,
            total_endpoints=total_endpoints,
            healthy_endpoints=healthy_count,
            unhealthy_endpoints=total_endpoints - healthy_count,
            overall_availability=overall_availability,
            overall_avg_response_time=overall_avg_response_time,
            active_alerts=0,  # Will be overridden by dashboard with correct count from AlertManager
            endpoints_status=endpoint_statuses
        )
    
    def get_current_outages(self):
        """Get current outages from the outage detector."""
        return self.outage_detector.get_current_outages()
    
    def get_degraded_endpoints(self):
        """Get currently degraded endpoints from the outage detector.""" 
        return self.outage_detector.get_degraded_endpoints()
    
    def get_outage_summary(self):
        """Get outage summary from the outage detector."""
        return self.outage_detector.get_outage_summary()
    
    def get_endpoint_outage_state(self, endpoint_name: str):
        """Get outage state for a specific endpoint."""
        return self.outage_detector.get_endpoint_state(endpoint_name)
    
    def get_outage_events(self):
        """Get recent outage events."""
        return getattr(self, '_outage_events', [])
    
    def create_outage_alerts(self):
        """Create alerts for recent outage events."""
        from alerting import AlertManager
        
        alerts = []
        recent_events = getattr(self, '_outage_events', [])
        
        for event in recent_events:
            alert = self.outage_detector.create_outage_alert(event)
            alerts.append(alert)
        
        # Clear processed events
        self._outage_events = []
        
        return alerts 