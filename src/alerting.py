import smtplib
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from colorama import Fore, Back, Style, init
import pytz

from models import Alert, SLOViolation, AlertSeverity
from config_loader import Config

# Initialize colorama for cross-platform colored terminal output
init()


class AlertChannel:
    """Base class for alert channels."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', True)
        self.logger = logging.getLogger(__name__)
    
    def send_alert(self, alert: Alert) -> bool:
        """Send an alert through this channel. Returns True if successful."""
        raise NotImplementedError
    
    def test_connection(self) -> bool:
        """Test if the channel is properly configured and reachable."""
        raise NotImplementedError


class ConsoleAlertChannel(AlertChannel):
    """Console-based alerting channel."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.use_colors = config.get('use_colors', True)
    
    def send_alert(self, alert: Alert) -> bool:
        """Send alert to console with colored output."""
        try:
            timestamp = alert.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            
            # Handle resolution notifications differently
            if alert.alert_type == "RESOLUTION":
                if self.use_colors:
                    color = Fore.GREEN + Style.BRIGHT
                    reset = Style.RESET_ALL
                else:
                    color = ""
                    reset = ""
                
                separator = "=" * 80
                alert_msg = f"""
{color}{separator}
✅ ALERT RESOLVED: {alert.endpoint_name}
{separator}{reset}
📅 Resolved: {timestamp}
🔗 Endpoint: {alert.endpoint_name}
👤 Resolved By: {alert.resolved_by or 'Unknown'}
📝 Resolution: {alert.resolution_reason or 'No reason provided'}
📊 Original Severity: {alert.severity.value.upper()}
{color}{separator}{reset}
"""
                print(alert_msg)
                return True
            
            # Choose colors based on severity for regular alerts
            if self.use_colors:
                if alert.severity == AlertSeverity.CRITICAL:
                    color = Fore.RED + Back.WHITE + Style.BRIGHT
                elif alert.severity == AlertSeverity.HIGH:
                    color = Fore.RED + Style.BRIGHT
                elif alert.severity == AlertSeverity.MEDIUM:
                    color = Fore.YELLOW + Style.BRIGHT
                else:
                    color = Fore.CYAN + Style.BRIGHT
                
                reset = Style.RESET_ALL
            else:
                color = ""
                reset = ""
            
            # Format alert message
            separator = "=" * 80
            alert_msg = f"""
{color}{separator}
🚨 ALERT: {alert.title}
{separator}{reset}
📅 Timestamp: {timestamp}
🔗 Endpoint: {alert.endpoint_name}
⚠️  Severity: {alert.severity.value.upper()}
📊 Type: {alert.alert_type}
📝 Description: {alert.description}
"""
            
            if alert.violation:
                alert_msg += f"""
📈 Current Value: {alert.violation.current_value:.2f}
🎯 Threshold: {alert.violation.threshold_value:.2f}
📋 Violation Type: {alert.violation.violation_type}
"""
            
            alert_msg += f"{color}{separator}{reset}\n"
            
            print(alert_msg)
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send console alert: {e}")
            return False
    
    def test_connection(self) -> bool:
        """Test console output."""
        try:
            print("Console alert channel test - OK")
            return True
        except Exception:
            return False


class EmailAlertChannel(AlertChannel):
    """Email-based alerting channel with MailHog support."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.smtp_server = config.get('smtp_server')
        self.smtp_port = config.get('smtp_port', 1025)
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.to_addresses = config.get('to_addresses', [])
        self.from_address = config.get('from_address', 'oncall@mailhog.local')
        self.use_tls = config.get('use_tls', False)
        self.timezone = config.get('timezone', 'UTC')
        
        # Set up timezone
        try:
            self.tz = pytz.timezone(self.timezone)
        except Exception:
            self.logger.warning(f"Invalid timezone '{self.timezone}', using UTC")
            self.tz = pytz.UTC
    
    def send_alert(self, alert: Alert) -> bool:
        """Send alert via email through MailHog."""
        missing_configs = []
        if not self.smtp_server:
            missing_configs.append("smtp_server")
        if not self.from_address:
            missing_configs.append("from_address")
        if not self.to_addresses:
            missing_configs.append("to_addresses")
        
        if missing_configs:
            self.logger.error(f"Email configuration incomplete. Missing: {', '.join(missing_configs)}")
            self.logger.debug(f"Current config: smtp_server='{self.smtp_server}', from_address='{self.from_address}', to_addresses={self.to_addresses}")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.from_address
            msg['To'] = ', '.join(self.to_addresses)
            msg['Subject'] = f"[{alert.severity.value.upper()}] {alert.title}"
            
            # Create email body
            body = self._format_email_body(alert)
            msg.attach(MIMEText(body, 'html'))
            
            # Send email through MailHog
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                # MailHog doesn't require authentication or TLS
                if self.use_tls:
                    server.starttls()
                
                if self.username and self.password:
                    server.login(self.username, self.password)
                
                server.send_message(msg)
            
            self.logger.info(f"Alert email sent to MailHog: {alert.id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send email alert to MailHog: {e}")
            return False
    
    def _format_email_body(self, alert: Alert) -> str:
        """Format alert as HTML email body with timezone support."""
        severity_colors = {
            'critical': '#FF0000',
            'high': '#FF6600',
            'medium': '#FFAA00',
            'low': '#00AA00'
        }
        
        color = severity_colors.get(alert.severity.value, '#666666')
        
        # Convert timestamp to configured timezone
        local_time = alert.timestamp.replace(tzinfo=pytz.UTC).astimezone(self.tz)
        formatted_time = local_time.strftime('%Y-%m-%d %H:%M:%S %Z')
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
        <div style="max-width: 600px;">
        
        <h2 style="color: {color}; border-bottom: 2px solid {color}; padding-bottom: 10px;">
        🚨 API Monitoring Alert
        </h2>
        
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
        <table style="width: 100%; border-collapse: collapse;">
        <tr><td style="padding: 8px; font-weight: bold; width: 150px;">Alert ID:</td><td style="padding: 8px;">{alert.id}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Timestamp:</td><td style="padding: 8px;">{formatted_time}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Endpoint:</td><td style="padding: 8px; font-family: monospace;">{alert.endpoint_name}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Severity:</td><td style="padding: 8px; color: {color}; font-weight: bold;">{alert.severity.value.upper()}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Type:</td><td style="padding: 8px;">{alert.alert_type}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold; vertical-align: top;">Description:</td><td style="padding: 8px;">{alert.description}</td></tr>
        """
        
        if alert.violation:
            html_body += f"""
        <tr><td colspan="2" style="padding: 15px 8px 5px 8px; font-weight: bold; color: #495057;">Violation Details:</td></tr>
        <tr><td style="padding: 8px; font-weight: bold; padding-left: 20px;">Current Value:</td><td style="padding: 8px; color: #e74c3c; font-weight: bold;">{alert.violation.current_value:.2f}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold; padding-left: 20px;">Threshold:</td><td style="padding: 8px;">{alert.violation.threshold_value:.2f}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold; padding-left: 20px;">Violation Type:</td><td style="padding: 8px;">{alert.violation.violation_type}</td></tr>
        """
        
        html_body += """
        </table>
        </div>
        
        <div style="margin-top: 20px; padding: 10px; background-color: #e9ecef; border-radius: 5px; font-size: 12px; color: #6c757d;">
        <p style="margin: 0;"><strong>BrightEdge API Monitoring System</strong></p>
        <p style="margin: 5px 0 0 0;">This alert was automatically generated by the monitoring system.</p>
        </div>
        
        </div>
        </body>
        </html>
        """
        
        return html_body
    
    def test_connection(self) -> bool:
        """Test MailHog SMTP connection."""
        if not self.smtp_server:
            return False
        
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                
                if self.username and self.password:
                    server.login(self.username, self.password)
                
            self.logger.info("MailHog connection test successful")
            return True
        except Exception as e:
            self.logger.error(f"MailHog connection test failed: {e}")
            return False


class WebhookAlertChannel(AlertChannel):
    """Webhook-based alerting channel."""
    
    def __init__(self, config: Dict[str, Any], verify_ssl: bool = True):
        super().__init__(config)
        self.url = config.get('url')
        self.headers = config.get('headers', {'Content-Type': 'application/json'})
        self.timeout = config.get('timeout', 10)
        self.retry_count = config.get('retry_count', 3)
        self.verify_ssl = verify_ssl
    
    def send_alert(self, alert: Alert) -> bool:
        """Send alert via webhook."""
        if not self.url:
            self.logger.error("Webhook URL not configured")
            return False
        
        payload = {
            'alert_id': alert.id,
            'timestamp': alert.timestamp.isoformat(),
            'endpoint_name': alert.endpoint_name,
            'alert_type': alert.alert_type,
            'severity': alert.severity.value,
            'title': alert.title,
            'description': alert.description,
            'resolved': alert.resolved
        }
        
        if alert.violation:
            payload['violation'] = alert.violation.to_dict()
        
        if alert.metadata:
            payload['metadata'] = alert.metadata
        
        for attempt in range(self.retry_count):
            try:
                response = requests.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout,
                    verify=self.verify_ssl
                )
                
                if response.status_code < 400:
                    self.logger.info(f"Alert sent via webhook: {alert.id}")
                    return True
                else:
                    self.logger.warning(f"Webhook returned status {response.status_code}: {response.text}")
                    
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Webhook attempt {attempt + 1} failed: {e}")
                if attempt == self.retry_count - 1:
                    self.logger.error(f"All webhook attempts failed for alert {alert.id}")
        
        return False
    
    def test_connection(self) -> bool:
        """Test webhook connectivity."""
        if not self.url:
            return False
        
        test_payload = {
            'test': True,
            'timestamp': datetime.now().isoformat(),
            'message': 'Webhook test from monitoring system'
        }
        
        try:
            response = requests.post(
                self.url,
                json=test_payload,
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            return response.status_code < 400
        except Exception:
            return False


class AlertManager:
    """Manages alerts and routes them to appropriate channels."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.channels: List[AlertChannel] = []
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        
        # Initialize alert channels
        self._initialize_channels()
    
    def _initialize_channels(self):
        """Initialize alert channels based on configuration."""
        if not self.config.alerting.enabled:
            self.logger.info("Alerting is disabled")
            return
        
        for channel_config in self.config.alerting.channels:
            channel_type = channel_config.get('type')
            if not channel_config.get('enabled', True):
                continue
            
            try:
                if channel_type == 'console':
                    channel = ConsoleAlertChannel(channel_config)
                elif channel_type == 'webhook':
                    channel = WebhookAlertChannel(channel_config, self.config.monitoring.verify_ssl)
                elif channel_type == 'email':
                    channel = EmailAlertChannel(channel_config)
                else:
                    self.logger.warning(f"Unknown alert channel type: {channel_type}")
                    continue
                
                self.channels.append(channel)
                self.logger.info(f"Initialized {channel_type} alert channel")
                
            except Exception as e:
                self.logger.error(f"Failed to initialize {channel_type} channel: {e}")
    
    def create_alert_from_violation(self, violation: SLOViolation) -> Alert:
        """Create an alert from an SLO violation."""
        alert_id = str(uuid.uuid4())
        
        title = f"SLO Violation: {violation.violation_type} for {violation.endpoint_name}"
        description = violation.description
        
        alert = Alert(
            id=alert_id,
            endpoint_name=violation.endpoint_name,
            alert_type='slo_violation',
            severity=violation.severity,
            timestamp=violation.timestamp,
            title=title,
            description=description,
            violation=violation,
            first_occurrence=violation.timestamp,
            last_sent_timestamp=None,  # Will be set when first sent
            repeat_count=0,
            original_title=title,  # Store original title for repeats
            original_description=description,  # Store original description for repeats
            metadata={
                'violation_type': violation.violation_type,
                'auto_generated': True
            }
        )
        
        return alert
    
    def send_alert(self, alert: Alert) -> bool:
        """Send alert through all configured channels."""
        if not self.config.alerting.enabled:
            return False
        
        success_count = 0
        total_channels = len(self.channels)
        
        if total_channels == 0:
            self.logger.warning("No alert channels configured")
            return False
        
        for channel in self.channels:
            try:
                if channel.send_alert(alert):
                    success_count += 1
            except Exception as e:
                self.logger.error(f"Error sending alert via {type(channel).__name__}: {e}")
        
        success = success_count > 0
        
        if success:
            # Update alert timing and repeat tracking
            current_time = datetime.now()
            if alert.last_sent_timestamp is None:
                # First time sending this alert
                alert.last_sent_timestamp = current_time
                alert.repeat_count = 0
                self.logger.info(f"Alert {alert.id} sent for first time via {success_count}/{total_channels} channels")
            else:
                # This is a repeat
                alert.last_sent_timestamp = current_time
                alert.repeat_count += 1
                self.logger.info(f"Alert {alert.id} repeated ({alert.repeat_count} times) via {success_count}/{total_channels} channels")
            
            # Store alert in active alerts
            self.active_alerts[alert.id] = alert
            
            # Add to history only if it's a new alert (first occurrence)
            if alert.repeat_count == 0:
                self.alert_history.append(alert)
            
            # Clean up old alerts history (keep last 1000)
            if len(self.alert_history) > 1000:
                self.alert_history = self.alert_history[-1000:]
                
        else:
            self.logger.error(f"Failed to send alert {alert.id} via any channel")
        
        return success
    
    def resolve_alert(self, alert_id: str, auto_resolved: bool = False, reason: str = None) -> bool:
        """Mark an alert as resolved and send resolution notifications."""
        if alert_id in self.active_alerts:
            alert = self.active_alerts[alert_id]
            alert.resolved = True
            alert.resolved_timestamp = datetime.now()
            
            # Set resolution details
            if auto_resolved:
                alert.resolved_by = "System (Auto-resolved)"
                alert.resolution_reason = reason or "Conditions have improved - SLO violations no longer occurring"
            else:
                alert.resolved_by = "User (Manual)"
                alert.resolution_reason = "Manually resolved via dashboard"
            
            # Send resolution notification
            self._send_resolution_notification(alert, auto_resolved)
            
            # Remove from active alerts
            del self.active_alerts[alert_id]
            
            resolution_type = "auto-resolved" if auto_resolved else "manually resolved"
            self.logger.info(f"Alert {alert_id} {resolution_type}: {alert.resolution_reason}")
            return True
        
        return False
    
    def _send_resolution_notification(self, alert: Alert, auto_resolved: bool):
        """Send notification when an alert is resolved."""
        if not self.config.alerting.enabled:
            return
        
        # Create a copy of the alert for resolution notification
        resolution_alert = Alert(
            id=alert.id,
            endpoint_name=alert.endpoint_name,
            title=f"🟢 RESOLVED: {alert.original_title or alert.title}",
            description=f"Alert has been resolved.\n\nOriginal issue: {alert.original_description or alert.description}\n\nResolution: {alert.resolution_reason}",
            severity=alert.severity,
            timestamp=alert.resolved_timestamp,
            resolved=True,
            resolved_timestamp=alert.resolved_timestamp,
            resolved_by=alert.resolved_by,
            resolution_reason=alert.resolution_reason,
            alert_type="RESOLUTION",
            violation=alert.violation,
            first_occurrence=alert.first_occurrence,
            last_sent_timestamp=alert.last_sent_timestamp,
            repeat_count=alert.repeat_count,
            original_title=alert.original_title,
            original_description=alert.original_description,
            metadata={
                'original_alert_id': alert.id,
                'auto_resolved': auto_resolved,
                'resolution_type': 'automatic' if auto_resolved else 'manual'
            }
        )
        
        # Send through all channels
        success_count = 0
        for channel in self.channels:
            try:
                if channel.send_alert(resolution_alert):
                    success_count += 1
            except Exception as e:
                self.logger.error(f"Error sending resolution notification via {type(channel).__name__}: {e}")
        
        if success_count > 0:
            self.logger.info(f"Resolution notification for alert {alert.id} sent via {success_count}/{len(self.channels)} channels")
        else:
            self.logger.warning(f"Failed to send resolution notification for alert {alert.id}")
    
    def process_violations(self, violations: Dict[str, List[SLOViolation]]) -> List[Alert]:
        """Process SLO violations and generate alerts."""
        new_alerts = []
        
        for endpoint_name, endpoint_violations in violations.items():
            for violation in endpoint_violations:
                # Check if we already have an active alert for this violation type
                existing_alert = self._find_existing_alert(endpoint_name, violation.violation_type)
                
                if not existing_alert:
                    # Create new alert
                    alert = self.create_alert_from_violation(violation)
                    if self.send_alert(alert):
                        new_alerts.append(alert)
                else:
                    # Update existing alert timestamp
                    existing_alert.timestamp = violation.timestamp
                    self.logger.debug(f"Updated existing alert {existing_alert.id}")
        
        return new_alerts
    
    def process_auto_resolution(self, current_sla_metrics: Dict[str, Any]) -> List[str]:
        """Check if any active alerts should be auto-resolved based on improved conditions."""
        if not self.config.alerting.enabled:
            return []
        
        resolved_alert_ids = []
        
        for alert_id, alert in list(self.active_alerts.items()):
            if alert.resolved:
                continue
            
            should_resolve = False
            resolution_reason = ""
            
            # Handle violation-based alerts (SLO violations)
            if alert.violation:
                # Get current SLA metrics for this endpoint
                endpoint_metrics = current_sla_metrics.get(alert.endpoint_name)
                if not endpoint_metrics:
                    continue
                
                # Check if the violation condition has been resolved
                violation_type = alert.violation.violation_type
                threshold_value = alert.violation.threshold_value
                
                if violation_type == 'availability':
                    current_availability = getattr(endpoint_metrics, 'availability_percentage', 0)
                    if current_availability >= threshold_value:
                        should_resolve = True
                        resolution_reason = f"Availability improved to {current_availability:.2f}% (above threshold of {threshold_value}%)"
                
                elif violation_type == 'response_time':
                    current_response_time = getattr(endpoint_metrics, 'avg_response_time_ms', float('inf'))
                    if current_response_time <= threshold_value:
                        should_resolve = True
                        resolution_reason = f"Response time improved to {current_response_time:.1f}ms (below threshold of {threshold_value}ms)"
                
                elif violation_type == 'error_rate':
                    current_error_rate = getattr(endpoint_metrics, 'error_rate_percentage', 100)
                    if current_error_rate <= threshold_value:
                        should_resolve = True
                        resolution_reason = f"Error rate improved to {current_error_rate:.2f}% (below threshold of {threshold_value}%)"
            
            # Handle outage-based alerts (from outage detector)
            elif alert.alert_type == "outage_detection":
                # Check if the endpoint is no longer in outage state
                # We need access to the monitoring service to check outage state
                # For now, we'll rely on manual resolution or outage recovery events
                continue
            
            if should_resolve:
                self.logger.info(f"Auto-resolving alert {alert_id}: {resolution_reason}")
                if self.resolve_alert(alert_id, auto_resolved=True, reason=resolution_reason):
                    resolved_alert_ids.append(alert_id)
        
        return resolved_alert_ids
    
    def _find_existing_alert(self, endpoint_name: str, violation_type: str) -> Optional[Alert]:
        """Find existing active alert for the same endpoint and violation type."""
        for alert in self.active_alerts.values():
            if (alert.endpoint_name == endpoint_name and 
                alert.violation and 
                alert.violation.violation_type == violation_type):
                return alert
        return None
    
    def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        return list(self.active_alerts.values())
    
    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """Get alert history with optional limit."""
        return self.alert_history[-limit:] if limit else self.alert_history
    
    def test_all_channels(self) -> Dict[str, bool]:
        """Test all configured alert channels."""
        results = {}
        
        for channel in self.channels:
            channel_name = type(channel).__name__
            try:
                results[channel_name] = channel.test_connection()
            except Exception as e:
                self.logger.error(f"Error testing {channel_name}: {e}")
                results[channel_name] = False
        
        return results
    
    def process_recurring_alerts(self) -> List[Alert]:
        """Process recurring alerts and resend those that need to be repeated."""
        if not self.config.alerting.enabled:
            return []
        
        recurring_alerts = []
        current_time = datetime.now()
        
        # Auto-resolve old alerts first
        self._auto_resolve_old_alerts(current_time)
        
        for alert in list(self.active_alerts.values()):
            if self._should_repeat_alert(alert, current_time):
                if self._can_repeat_alert(alert):
                    # Ensure original title and description are set (fallback for existing alerts)
                    if alert.original_title is None:
                        alert.original_title = alert.title
                    if alert.original_description is None:
                        alert.original_description = alert.description
                    
                    # Calculate what the repeat number will be after this send
                    next_repeat_number = alert.repeat_count + 1
                    
                    # Update the alert title to indicate it's a repeat
                    alert.title = f"[REPEAT #{next_repeat_number}] {alert.original_title}"
                    
                    # Update description to show duration
                    duration = current_time - alert.first_occurrence
                    hours = int(duration.total_seconds() // 3600)
                    minutes = int((duration.total_seconds() % 3600) // 60)
                    duration_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                    
                    alert.description = f"{alert.original_description}\n\n[ONGOING] This alert has been active for {duration_str} (repeat #{next_repeat_number})"
                    
                    if self.send_alert(alert):
                        recurring_alerts.append(alert)
                else:
                    # Max repeats reached, auto-resolve
                    self.logger.info(f"Alert {alert.id} reached max repeats ({self.config.alerting.max_repeats}), auto-resolving")
                    self.resolve_alert(alert.id, auto_resolved=True, reason="Maximum repeat count reached")
        
        return recurring_alerts
    
    def _should_repeat_alert(self, alert: Alert, current_time: datetime) -> bool:
        """Check if an alert should be repeated based on time elapsed."""
        if alert.resolved or alert.last_sent_timestamp is None:
            return False
        
        minutes_since_last_sent = (current_time - alert.last_sent_timestamp).total_seconds() / 60
        return minutes_since_last_sent >= self.config.alerting.repeat_interval_minutes
    
    def _can_repeat_alert(self, alert: Alert) -> bool:
        """Check if an alert can be repeated (hasn't exceeded max repeats)."""
        if self.config.alerting.max_repeats <= 0:
            return True  # Unlimited repeats
        return alert.repeat_count < self.config.alerting.max_repeats
    
    def _auto_resolve_old_alerts(self, current_time: datetime):
        """Auto-resolve alerts that are older than the configured threshold."""
        if self.config.alerting.auto_resolve_after_hours <= 0:
            return  # Auto-resolve disabled
        
        threshold_hours = self.config.alerting.auto_resolve_after_hours
        
        for alert_id, alert in list(self.active_alerts.items()):
            if alert.first_occurrence:
                hours_since_first = (current_time - alert.first_occurrence).total_seconds() / 3600
                if hours_since_first >= threshold_hours:
                    self.logger.info(f"Auto-resolving alert {alert_id} after {hours_since_first:.1f} hours")
                    self.resolve_alert(alert_id, auto_resolved=True, reason=f"Alert auto-resolved after {threshold_hours} hours") 