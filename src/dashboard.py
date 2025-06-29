"""
Simple web dashboard for the monitoring system.
Provides REST API endpoints and basic HTML interface for viewing metrics.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
from threading import Thread
import socket

try:
    from flask import Flask, render_template_string, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

from config_loader import Config
from models import HealthStatus


class DashboardServer:
    """Simple web dashboard for monitoring system."""
    
    def __init__(self, config: Config, monitoring_service=None, alert_manager=None, data_manager=None):
        if not FLASK_AVAILABLE:
            raise ImportError("flask package required for dashboard")
        
        self.config = config
        self.monitoring_service = monitoring_service
        self.alert_manager = alert_manager
        self.data_manager = data_manager
        self.logger = logging.getLogger(__name__)
        
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'monitoring-dashboard-secret'
        
        # Disable Flask's default logging
        logging.getLogger('werkzeug').setLevel(logging.WARNING)
        
        self._setup_routes()
        self.running = False
    
    def _setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.route('/')
        def index():
            """Main dashboard page."""
            return render_template_string(self._get_dashboard_template())
        
        @self.app.route('/api/health')
        def api_health():
            """Get current health status."""
            try:
                if self.monitoring_service:
                    health = self.monitoring_service.get_health_status()
                    if health:
                        health_dict = health.to_dict()
                        # Fix active alerts count by getting it from AlertManager
                        if self.alert_manager:
                            health_dict['active_alerts'] = len(self.alert_manager.get_active_alerts())
                        
                        # Add outage information
                        if hasattr(self.monitoring_service, 'get_current_outages'):
                            current_outages = self.monitoring_service.get_current_outages()
                            degraded_endpoints = self.monitoring_service.get_degraded_endpoints()
                            
                            health_dict['outage_status'] = {
                                'current_outages': len(current_outages),
                                'degraded_endpoints': len(degraded_endpoints),
                                'outage_details': [outage.to_dict() for outage in current_outages],
                                'degraded_details': [endpoint.to_dict() for endpoint in degraded_endpoints]
                            }
                        
                        return jsonify(health_dict)
                    return jsonify({})
                return jsonify({'error': 'Monitoring service not available'}), 503
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/alerts')
        def api_alerts():
            """Get current active alerts."""
            try:
                if self.alert_manager:
                    alerts = self.alert_manager.get_active_alerts()
                    return jsonify([alert.to_dict() for alert in alerts])
                return jsonify([])
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/alerts/history')
        def api_alerts_history():
            """Get alert history."""
            try:
                limit = request.args.get('limit', 50, type=int)
                if self.alert_manager:
                    alerts = self.alert_manager.get_alert_history(limit)
                    return jsonify([alert.to_dict() for alert in alerts])
                return jsonify([])
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/sla')
        def api_sla():
            """Get SLA metrics."""
            try:
                if self.monitoring_service:
                    window_hours = request.args.get('window', 1, type=int)
                    metrics = self.monitoring_service.analyze_sla_compliance(window_hours)
                    
                    # Convert to JSON-serializable format
                    result = {}
                    for endpoint_name, sla_metrics in metrics.items():
                        result[endpoint_name] = {
                            'endpoint_name': sla_metrics.endpoint_name,
                            'time_window_start': sla_metrics.time_window_start.isoformat(),
                            'time_window_end': sla_metrics.time_window_end.isoformat(),
                            'total_requests': sla_metrics.total_requests,
                            'successful_requests': sla_metrics.successful_requests,
                            'failed_requests': sla_metrics.failed_requests,
                            'availability_percentage': sla_metrics.availability_percentage,
                            'avg_response_time_ms': sla_metrics.avg_response_time_ms,
                            'max_response_time_ms': sla_metrics.max_response_time_ms,
                            'min_response_time_ms': sla_metrics.min_response_time_ms,
                            'p95_response_time_ms': sla_metrics.p95_response_time_ms,
                            'p99_response_time_ms': sla_metrics.p99_response_time_ms,
                            'error_rate_percentage': sla_metrics.error_rate_percentage
                        }
                    
                    return jsonify(result)
                return jsonify({})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/config')
        def api_config():
            """Get monitoring configuration (safe subset)."""
            try:
                return jsonify({
                    'endpoints': [
                        {
                            'name': ep.name,
                            'url': ep.url,
                            'method': ep.method,
                            'expected_status': ep.expected_status,
                            'sla': ep.sla,
                            'slo': ep.slo
                        }
                        for ep in self.config.endpoints
                    ],
                    'monitoring': {
                        'interval_seconds': self.config.monitoring.interval_seconds,
                        'timeout_seconds': self.config.monitoring.timeout_seconds,
                        'max_workers': self.config.monitoring.max_workers
                    },
                    'alerting': {
                        'enabled': self.config.alerting.enabled,
                        'repeat_interval_minutes': self.config.alerting.repeat_interval_minutes,
                        'max_repeats': self.config.alerting.max_repeats,
                        'auto_resolve_after_hours': self.config.alerting.auto_resolve_after_hours
                    }
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/trigger-monitoring', methods=['POST'])
        def api_trigger_monitoring():
            """Manually trigger a monitoring cycle."""
            try:
                if self.monitoring_service:
                    # Run monitoring cycle in background
                    import threading
                    thread = threading.Thread(target=self.monitoring_service.run_single_cycle)
                    thread.daemon = True
                    thread.start()
                    return jsonify({'message': 'Monitoring cycle triggered successfully'})
                return jsonify({'error': 'Monitoring service not available'}), 503
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/alerts/<alert_id>/resolve', methods=['POST'])
        def api_resolve_alert(alert_id):
            """Resolve a specific alert."""
            try:
                if self.alert_manager:
                    success = self.alert_manager.resolve_alert(alert_id)
                    if success:
                        return jsonify({'message': 'Alert resolved successfully'})
                    else:
                        return jsonify({'error': 'Alert not found'}), 404
                return jsonify({'error': 'Alert manager not available'}), 503
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/test-alerts', methods=['POST'])
        def api_test_alerts():
            """Test all alert channels."""
            try:
                if self.alert_manager:
                    results = self.alert_manager.test_all_channels()
                    return jsonify({
                        'results': results,
                        'all_passed': all(results.values())
                    })
                return jsonify({'error': 'Alert manager not available'}), 503
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/outages')
        def api_outages():
            """Get detailed outage information."""
            try:
                if self.monitoring_service and hasattr(self.monitoring_service, 'get_outage_summary'):
                    outage_summary = self.monitoring_service.get_outage_summary()
                    return jsonify(outage_summary)
                return jsonify({'error': 'Outage detection not available'}), 503
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/outages/<endpoint_name>')
        def api_endpoint_outage(endpoint_name):
            """Get outage state for a specific endpoint."""
            try:
                if self.monitoring_service and hasattr(self.monitoring_service, 'get_endpoint_outage_state'):
                    outage_state = self.monitoring_service.get_endpoint_outage_state(endpoint_name)
                    if outage_state:
                        return jsonify(outage_state.to_dict())
                    return jsonify({'error': f'Endpoint {endpoint_name} not found'}), 404
                return jsonify({'error': 'Outage detection not available'}), 503
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/system-info')
        def api_system_info():
            """Get system information and statistics."""
            try:
                info = {
                    'timestamp': datetime.now().isoformat(),
                    'uptime': 'Unknown',  # Could be tracked if needed
                    'total_endpoints': len(self.config.endpoints),
                    'monitoring_interval': self.config.monitoring.interval_seconds,
                    'alert_channels': len(self.config.alerting.channels) if self.config.alerting.enabled else 0,
                    'services': {
                        'monitoring': self.monitoring_service is not None,
                        'alerting': self.alert_manager is not None,
                        'data_storage': self.data_manager is not None
                    }
                }
                
                # Add alert statistics if available
                if self.alert_manager:
                    active_alerts = self.alert_manager.get_active_alerts()
                    alert_history = self.alert_manager.get_alert_history(100)
                    
                    # Count by severity
                    severity_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
                    for alert in active_alerts:
                        severity_counts[alert.severity.value] += 1
                    
                    info['alert_stats'] = {
                        'active_total': len(active_alerts),
                        'history_total': len(alert_history),
                        'by_severity': severity_counts
                    }
                
                return jsonify(info)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/metrics')
        def metrics():
            """Prometheus metrics endpoint for direct scraping."""
            try:
                if (self.data_manager and 
                    hasattr(self.data_manager, 'storage') and 
                    hasattr(self.data_manager.storage, 'get_registry')):
                    # Get metrics from Prometheus storage
                    from prometheus_client import generate_latest
                    registry = self.data_manager.storage.get_registry()
                    metrics_data = generate_latest(registry)
                    return metrics_data, 200, {'Content-Type': 'text/plain; charset=utf-8'}
                else:
                    # Return basic metrics if Prometheus storage not available
                    return "# No metrics available\n", 200, {'Content-Type': 'text/plain; charset=utf-8'}
            except Exception as e:
                self.logger.error(f"Error generating metrics: {e}")
                return f"# Error generating metrics: {e}\n", 500, {'Content-Type': 'text/plain; charset=utf-8'}
    
    def _get_dashboard_template(self) -> str:
        """Get HTML template for dashboard."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BrightEdge API Monitoring Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            padding: 20px;
            color: #e0e0e0;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            background: rgba(40, 40, 60, 0.95);
            backdrop-filter: blur(10px);
            color: #e0e0e0;
            padding: 30px;
            border-radius: 16px;
            margin-bottom: 30px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            border: 1px solid rgba(100, 100, 120, 0.3);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .header p {
            color: #b0b0b0;
        }
        
        .header-info {
            display: flex;
            gap: 20px;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 500;
            font-size: 0.9em;
        }
        
        .status-healthy {
            background: rgba(39, 174, 96, 0.3);
            color: #2ecc71;
            border: 1px solid #27ae60;
        }
        
        .status-unhealthy {
            background: rgba(231, 76, 60, 0.3);
            color: #e74c3c;
            border: 1px solid #e74c3c;
        }
        
        .control-panel {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: white;
        }
        
        .btn-primary {
            background: #3498db;
            color: white;
        }
        
        .btn-success {
            background: #27ae60;
            color: white;
        }
        
        .btn-warning {
            background: #f39c12;
            color: white;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .metrics-overview {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .metric-card {
            background: rgba(40, 40, 60, 0.95);
            backdrop-filter: blur(10px);
            padding: 25px;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            border: 1px solid rgba(100, 100, 120, 0.3);
            transition: transform 0.3s ease;
            color: #e0e0e0;
        }
        
        .metric-card:hover {
            transform: translateY(-5px);
        }
        
        .metric-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .metric-title {
            font-size: 0.9em;
            color: #b0b0b0;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .metric-icon {
            font-size: 1.5em;
            opacity: 0.8;
        }
        
        .metric-value {
            font-size: 2.5em;
            font-weight: 700;
            color: #e0e0e0;
            margin-bottom: 10px;
        }
        
        .metric-subtitle {
            font-size: 0.85em;
            color: #b0b0b0;
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: rgba(60, 60, 80, 0.8);
            border-radius: 4px;
            margin-top: 15px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        
        .progress-success { background: linear-gradient(90deg, #27ae60, #2ecc71); }
        .progress-warning { background: linear-gradient(90deg, #f39c12, #e67e22); }
        .progress-danger { background: linear-gradient(90deg, #e74c3c, #c0392b); }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 30px;
            margin-bottom: 30px;
        }
        
        .main-content {
            display: flex;
            flex-direction: column;
            gap: 30px;
        }
        
        .sidebar {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        
        .panel {
            background: rgba(40, 40, 60, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            border: 1px solid rgba(100, 100, 120, 0.3);
            overflow: hidden;
        }
        
        .panel-header {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 20px 25px;
            font-weight: 600;
            font-size: 1.1em;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .panel-content {
            padding: 25px;
            color: #e0e0e0;
        }
        
        .endpoint-list {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        
        .endpoint-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: rgba(30, 30, 50, 0.8);
            border-radius: 10px;
            transition: all 0.3s ease;
            border: 1px solid rgba(100, 100, 120, 0.2);
        }
        
        .endpoint-item:hover {
            background: rgba(50, 50, 70, 0.8);
            transform: translateX(5px);
        }
        
        .endpoint-info h4 {
            margin-bottom: 5px;
            color: #e0e0e0;
        }
        
        .endpoint-metrics {
            display: flex;
            gap: 20px;
            font-size: 0.85em;
            color: #b0b0b0;
        }
        
        .endpoint-status {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1.2em;
        }
        
        .status-badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 500;
        }
        
        .badge-success {
            background: rgba(39, 174, 96, 0.3);
            color: #2ecc71;
        }
        
        .badge-danger {
            background: rgba(231, 76, 60, 0.3);
            color: #e74c3c;
        }
        
        .alert-item {
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            border-left: 4px solid;
            position: relative;
            background: rgba(30, 30, 50, 0.8);
        }
        
        .alert-critical {
            background: rgba(231, 76, 60, 0.2);
            border-color: #e74c3c;
        }
        
        .alert-high {
            background: rgba(230, 126, 34, 0.2);
            border-color: #e67e22;
        }
        
        .alert-medium {
            background: rgba(243, 156, 18, 0.2);
            border-color: #f39c12;
        }
        
        .alert-low {
            background: rgba(52, 152, 219, 0.2);
            border-color: #3498db;
        }
        
        .alert-resolved {
            opacity: 0.7;
            border-left-color: #27ae60 !important;
            background: rgba(39, 174, 96, 0.1) !important;
        }
        
        .alert-header {
            display: flex;
            justify-content: between;
            align-items: center;
            margin-bottom: 8px;
        }
        
        .alert-title {
            font-weight: 600;
            color: #e0e0e0;
            margin-bottom: 5px;
        }
        
        .alert-meta {
            display: flex;
            gap: 15px;
            font-size: 0.85em;
            color: #b0b0b0;
            margin-bottom: 10px;
        }
        
        .alert-actions {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }
        
        .btn-small {
            padding: 6px 12px;
            font-size: 0.8em;
            border-radius: 6px;
        }
        
        .system-stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        
        .stat-item {
            text-align: center;
            padding: 15px;
            background: rgba(30, 30, 50, 0.8);
            border-radius: 8px;
            border: 1px solid rgba(100, 100, 120, 0.2);
        }
        
        .stat-value {
            font-size: 1.5em;
            font-weight: 600;
            color: #e0e0e0;
        }
        
        .stat-label {
            font-size: 0.8em;
            color: #b0b0b0;
            margin-top: 5px;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #b0b0b0;
        }
        
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(100, 100, 120, 0.3);
            border-top: 3px solid #3498db;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 8px;
            color: white;
            font-weight: 500;
            z-index: 1000;
            transform: translateX(400px);
            transition: transform 0.3s ease;
        }
        
        .notification.show {
            transform: translateX(0);
        }
        
        .notification-success {
            background: #27ae60;
        }
        
        .notification-error {
            background: #e74c3c;
        }
        
        #last-update {
            color: #b0b0b0 !important;
        }
        
        /* Alert Details Modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 2000;
        }
        
        .modal-overlay.show {
            display: flex;
        }
        
        .modal-content {
            background: rgba(40, 40, 60, 0.98);
            backdrop-filter: blur(20px);
            border-radius: 16px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            border: 1px solid rgba(100, 100, 120, 0.3);
            color: #e0e0e0;
        }
        
        .modal-header {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 20px 25px;
            border-radius: 16px 16px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .modal-title {
            font-size: 1.3em;
            font-weight: 600;
            margin: 0;
        }
        
        .modal-close {
            background: none;
            border: none;
            color: white;
            font-size: 1.5em;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.3s ease;
        }
        
        .modal-close:hover {
            background: rgba(255, 255, 255, 0.2);
        }
        
        .modal-body {
            padding: 25px;
        }
        
        .alert-detail-section {
            margin-bottom: 25px;
            padding: 20px;
            background: rgba(30, 30, 50, 0.6);
            border-radius: 12px;
            border: 1px solid rgba(100, 100, 120, 0.2);
        }
        
        .alert-detail-section h3 {
            margin: 0 0 15px 0;
            color: #667eea;
            font-size: 1.1em;
            border-bottom: 1px solid rgba(100, 100, 120, 0.3);
            padding-bottom: 8px;
        }
        
        .detail-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
        }
        
        .detail-item {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        
        .detail-label {
            font-size: 0.85em;
            color: #b0b0b0;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .detail-value {
            color: #e0e0e0;
            font-weight: 600;
        }
        
        .detail-value.critical { color: #e74c3c; }
        .detail-value.high { color: #e67e22; }
        .detail-value.medium { color: #f39c12; }
        .detail-value.low { color: #3498db; }
        .detail-value.success { color: #27ae60; }
        
        .alert-description {
            background: rgba(20, 20, 40, 0.8);
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            font-style: italic;
            line-height: 1.6;
        }
        
        .modal-footer {
            padding: 20px 25px;
            border-top: 1px solid rgba(100, 100, 120, 0.3);
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }
        
        @media (max-width: 768px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
            
            .metrics-overview {
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            }
            
            .header {
                flex-direction: column;
                text-align: center;
            }
            
            .control-panel {
                justify-content: center;
            }
            
            .modal-content {
                width: 95%;
                max-height: 90vh;
                margin: 10px;
            }
            
            .detail-grid {
                grid-template-columns: 1fr;
            }
            
            .modal-footer {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header with System Overview -->
        <div class="header">
            <div>
                <h1>🚀 API Monitoring Dashboard</h1>
                <p>Real-Time Monitoring with SLA/SLO Tracking & Intelligent Alerting</p>
            </div>
            <div class="header-info">
                <div id="system-status" class="status-indicator">
                    <span class="spinner"></span>
                    <span>Loading...</span>
                </div>
                <div id="last-update" style="font-size: 0.9em; color: #b0b0b0;">
                    Loading... (Auto-refresh every 30s)
                </div>
            </div>
        </div>

        <!-- Control Panel -->
        <div class="control-panel">
            <a class="btn btn-success" href="http://localhost:3000/d/80d19551-e6f4-4a70-b161-2058eb42e811/api-monitoring?orgId=1&from=now-30m&to=now&timezone=browser&var-endpoint=$__all" target="_blank">
                📊 Grafana Dashboard
            </a>
            <a class="btn btn-warning" href="http://localhost:8025/" target="_blank" title="View MailHog email interface to see sent alerts">
                📧 MailHog Alerts
            </a>
            <button class="btn btn-primary" onclick="toggleAutoRefresh()" title="Toggle automatic data refresh every 30 seconds">
                <span id="auto-refresh-text">⏸️ Pause Auto-refresh (30s)</span>
            </button>
        </div>

        <!-- Key Metrics Overview -->
        <div class="metrics-overview">
            <div class="metric-card">
                <div class="metric-header">
                    <div class="metric-title">System Health</div>
                    <div class="metric-icon">💚</div>
                </div>
                <div class="metric-value" id="overall-health">--</div>
                <div class="metric-subtitle" id="health-subtitle">Checking system status...</div>
                <div class="progress-bar">
                    <div class="progress-fill progress-success" id="health-progress" style="width: 0%"></div>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-header">
                    <div class="metric-title">Availability</div>
                    <div class="metric-icon">📊</div>
                </div>
                <div class="metric-value" id="overall-availability">--%</div>
                <div class="metric-subtitle">Average across all endpoints</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="availability-progress" style="width: 0%"></div>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-header">
                    <div class="metric-title">Response Time</div>
                    <div class="metric-icon">⚡</div>
                </div>
                <div class="metric-value" id="avg-response-time">--ms</div>
                <div class="metric-subtitle">Average response time</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="response-time-progress" style="width: 0%"></div>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-header">
                    <div class="metric-title">Active Alerts</div>
                    <div class="metric-icon">🚨</div>
                </div>
                <div class="metric-value" id="active-alerts">--</div>
                <div class="metric-subtitle" id="alerts-subtitle">No alerts</div>
                <div id="alert-severity-breakdown" style="margin-top: 10px;"></div>
            </div>
        </div>

        <!-- Main Dashboard Grid -->
        <div class="dashboard-grid">
            <div class="main-content">
                <!-- Endpoint Status Panel -->
                <div class="panel">
                    <div class="panel-header">
                        <span>📊 Endpoint Status</span>
                        <span id="endpoints-count">Loading...</span>
                    </div>
                    <div class="panel-content">
                        <div class="endpoint-list" id="endpoints-container">
                            <div class="loading">
                                <span class="spinner"></span>
                                <div style="margin-top: 10px;">Loading endpoint data...</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Active Alerts Panel -->
                <div class="panel">
                    <div class="panel-header">
                        <span>🚨 Active Alerts</span>
                        <span id="alerts-count">Loading...</span>
                    </div>
                    <div class="panel-content">
                        <div id="alerts-container">
                            <div class="loading">
                                <span class="spinner"></span>
                                <div style="margin-top: 10px;">Loading alerts...</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="sidebar">
                <!-- System Information Panel -->
                <div class="panel">
                    <div class="panel-header">
                        <span>⚙️ System Info</span>
                    </div>
                    <div class="panel-content">
                        <div class="system-stats" id="system-info-container">
                            <div class="loading">
                                <span class="spinner"></span>
                                <div style="margin-top: 10px;">Loading system info...</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Quick Actions Panel -->
                <div class="panel">
                    <div class="panel-header">
                        <span>⚡ Quick Actions</span>
                    </div>
                    <div class="panel-content">
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            <button class="btn btn-primary" onclick="viewSLAReport()">
                                📈 View SLA Report
                            </button>
                            <button class="btn btn-primary" onclick="exportData()">
                                💾 Export Data
                            </button>
                            <button class="btn btn-primary" onclick="viewMetrics()">
                                📊 Prometheus Metrics
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Notification Container -->
    <div id="notification" class="notification"></div>

    <!-- Alert Details Modal -->
    <div id="alert-details-modal" class="modal-overlay">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="modal-title">🚨 Alert Details</h2>
                <button class="modal-close" onclick="closeAlertDetailsModal()">&times;</button>
            </div>
            <div class="modal-body" id="alert-details-content">
                <!-- Content will be populated by JavaScript -->
            </div>
            <div class="modal-footer">
                <button class="btn btn-primary" onclick="resolveAlertFromModal()">
                    ✓ Resolve Alert
                </button>
                <button class="btn btn-primary" onclick="closeAlertDetailsModal()">
                    ✕ Close
                </button>
            </div>
        </div>
    </div>

    <script>
        let autoRefreshEnabled = true;
        let autoRefreshInterval;

        // Initialize dashboard
        document.addEventListener('DOMContentLoaded', function() {
            refreshData();
            startAutoRefresh();
        });

        function startAutoRefresh() {
            if (autoRefreshInterval) clearInterval(autoRefreshInterval);
            autoRefreshInterval = setInterval(refreshData, 30000);
        }

        function toggleAutoRefresh() {
            autoRefreshEnabled = !autoRefreshEnabled;
            const button = document.getElementById('auto-refresh-text');
            
            if (autoRefreshEnabled) {
                button.textContent = '⏸️ Pause Auto-refresh (30s)';
                button.parentElement.className = 'btn btn-primary';
                startAutoRefresh();
                updateLastRefresh();
                showNotification('Auto-refresh enabled - updating every 30 seconds', 'success');
            } else {
                button.textContent = '▶️ Resume Auto-refresh';
                button.parentElement.className = 'btn btn-warning';
                if (autoRefreshInterval) clearInterval(autoRefreshInterval);
                updateLastRefresh();
                showNotification('Auto-refresh paused - click to resume', 'error');
            }
        }

        async function refreshData() {
            try {
                updateLastRefresh();
                
                const [health, alerts, systemInfo] = await Promise.all([
                    fetch('/api/health').then(r => r.json()),
                    fetch('/api/alerts').then(r => r.json()),
                    fetch('/api/system-info').then(r => r.json())
                ]);
                
                updateSystemStatus(health, alerts);
                updateMetrics(health);
                updateEndpoints(health);
                updateAlerts(alerts);
                updateSystemInfo(systemInfo);
                
            } catch (error) {
                console.error('Error fetching data:', error);
                showNotification('Error fetching data', 'error');
            }
        }

        function updateLastRefresh() {
            const refreshText = autoRefreshEnabled ? 
                `Last updated: ${new Date().toLocaleTimeString()}` :
                `Last updated: ${new Date().toLocaleTimeString()} (Auto-refresh paused)`;
            document.getElementById('last-update').textContent = refreshText;
        }

        function updateSystemStatus(health, alerts) {
            const statusElement = document.getElementById('system-status');
            const isHealthy = health.is_healthy;
            const criticalAlerts = alerts.filter(a => a.severity === 'critical').length;
            
            statusElement.className = isHealthy && criticalAlerts === 0 ? 
                'status-indicator status-healthy' : 'status-indicator status-unhealthy';
            
            const statusText = isHealthy ? 
                (criticalAlerts > 0 ? '⚠️ Healthy with Alerts' : '✅ All Systems Healthy') :
                '❌ System Issues Detected';
                
            statusElement.innerHTML = `<span>${statusText}</span>`;
        }

        function updateMetrics(health) {
            // Overall Health
            const healthValue = document.getElementById('overall-health');
            const healthSubtitle = document.getElementById('health-subtitle');
            const healthProgress = document.getElementById('health-progress');
            
            if (health.is_healthy) {
                healthValue.textContent = 'HEALTHY';
                healthSubtitle.textContent = `${health.healthy_endpoints}/${health.total_endpoints} endpoints healthy`;
                healthProgress.style.width = '100%';
                healthProgress.className = 'progress-fill progress-success';
            } else {
                healthValue.textContent = 'ISSUES';
                healthSubtitle.textContent = `${health.unhealthy_endpoints} endpoints with issues`;
                const healthPercent = (health.healthy_endpoints / health.total_endpoints) * 100;
                healthProgress.style.width = healthPercent + '%';
                healthProgress.className = healthPercent > 80 ? 'progress-fill progress-warning' : 'progress-fill progress-danger';
            }

            // Availability
            const availability = health.overall_availability || 0;
            document.getElementById('overall-availability').textContent = availability.toFixed(2) + '%';
            const availabilityProgress = document.getElementById('availability-progress');
            availabilityProgress.style.width = availability + '%';
            availabilityProgress.className = availability >= 99 ? 'progress-fill progress-success' :
                availability >= 95 ? 'progress-fill progress-warning' : 'progress-fill progress-danger';

            // Response Time
            const responseTime = health.overall_avg_response_time || 0;
            document.getElementById('avg-response-time').textContent = responseTime.toFixed(0) + 'ms';
            const responseProgress = document.getElementById('response-time-progress');
            const responsePercent = Math.min(100, Math.max(0, 100 - (responseTime / 50))); // Scale for visualization
            responseProgress.style.width = responsePercent + '%';
            responseProgress.className = responseTime <= 1000 ? 'progress-fill progress-success' :
                responseTime <= 3000 ? 'progress-fill progress-warning' : 'progress-fill progress-danger';

            // Active Alerts
            const alertsCount = health.active_alerts || 0;
            document.getElementById('active-alerts').textContent = alertsCount;
            document.getElementById('alerts-subtitle').textContent = 
                alertsCount === 0 ? 'No active alerts' : `${alertsCount} alert${alertsCount > 1 ? 's' : ''} require attention`;
        }

        function updateEndpoints(health) {
            const container = document.getElementById('endpoints-container');
            const countElement = document.getElementById('endpoints-count');
            
            if (!health.endpoints_status) {
                container.innerHTML = '<div class="loading">No endpoint data available</div>';
                countElement.textContent = '0 endpoints';
                return;
            }

            const endpoints = Object.entries(health.endpoints_status);
            countElement.textContent = `${endpoints.length} endpoints`;

            container.innerHTML = endpoints.map(([name, status]) => `
                <div class="endpoint-item">
                    <div class="endpoint-info">
                        <h4>${name}</h4>
                        <div class="endpoint-metrics">
                            <span>📊 ${(status.availability_percentage || 0).toFixed(1)}% uptime</span>
                            <span>⚡ ${(status.avg_response_time_ms || 0).toFixed(0)}ms avg</span>
                        </div>
                    </div>
                    <div class="endpoint-status">
                        <span class="status-badge ${status.healthy ? 'badge-success' : 'badge-danger'}">
                            ${status.healthy ? 'HEALTHY' : 'ISSUES'}
                        </span>
                        <span>${status.healthy ? '✅' : '❌'}</span>
                    </div>
                </div>
            `).join('');
        }

        function updateAlerts(alerts) {
            // Store alerts globally for modal access
            currentAlerts = alerts;
            
            const container = document.getElementById('alerts-container');
            const countElement = document.getElementById('alerts-count');
            const breakdownElement = document.getElementById('alert-severity-breakdown');
            
            countElement.textContent = `${alerts.length} active`;

            // Severity breakdown
            const severityCount = { critical: 0, high: 0, medium: 0, low: 0 };
            alerts.forEach(alert => severityCount[alert.severity]++);
            
            breakdownElement.innerHTML = Object.entries(severityCount)
                .filter(([_, count]) => count > 0)
                .map(([severity, count]) => `
                    <span style="font-size: 0.8em; margin-right: 10px;">
                        ${severity.toUpperCase()}: ${count}
                    </span>
                `).join('');

            if (alerts.length === 0) {
                container.innerHTML = '<div style="text-align: center; padding: 20px; color: #27ae60;">✅ No active alerts - All systems operating normally</div>';
                return;
            }

            container.innerHTML = alerts.map(alert => `
                <div class="alert-item alert-${alert.severity}${alert.resolved ? ' alert-resolved' : ''}">
                    <div class="alert-title">
                        ${alert.resolved ? '✅ ' : ''}${alert.title}
                        ${alert.resolved ? ' <span style="color: #27ae60; font-size: 0.8em;">[RESOLVED]</span>' : ''}
                    </div>
                    <div class="alert-meta">
                        <span>🏷️ ${alert.endpoint_name}</span>
                        <span>⚠️ ${alert.severity.toUpperCase()}</span>
                        <span>📅 ${new Date(alert.timestamp).toLocaleString()}</span>
                        ${alert.repeat_count > 0 ? `<span>🔄 Repeat #${alert.repeat_count}</span>` : ''}
                        ${alert.resolved && alert.resolved_by ? `<span>👤 ${alert.resolved_by}</span>` : ''}
                    </div>
                    <div style="font-size: 0.9em; color: #b0b0b0; margin-bottom: 10px;">
                        ${alert.description}
                        ${alert.resolved && alert.resolution_reason ? `<br><em style="color: #27ae60;">Resolution: ${alert.resolution_reason}</em>` : ''}
                    </div>
                    <div class="alert-actions">
                        ${!alert.resolved ? `
                        <button class="btn btn-small btn-primary" onclick="resolveAlert('${alert.id}')">
                            ✓ Resolve
                        </button>
                        ` : ''}
                        <button class="btn btn-small btn-warning" onclick="viewAlertDetails('${alert.id}')">
                            👁️ Details
                        </button>
                    </div>
                </div>
            `).join('');
        }

        function updateSystemInfo(systemInfo) {
            const container = document.getElementById('system-info-container');
            
            if (!systemInfo) {
                container.innerHTML = '<div class="loading">System info unavailable</div>';
                return;
            }

            container.innerHTML = `
                <div class="stat-item">
                    <div class="stat-value">${systemInfo.total_endpoints}</div>
                    <div class="stat-label">Endpoints</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${systemInfo.monitoring_interval}s</div>
                    <div class="stat-label">Check Interval</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${systemInfo.alert_channels}</div>
                    <div class="stat-label">Alert Channels</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${Object.values(systemInfo.services || {}).filter(Boolean).length}</div>
                    <div class="stat-label">Active Services</div>
                </div>
            `;
        }

        // Action functions
        async function triggerMonitoring() {
            try {
                const response = await fetch('/api/trigger-monitoring', { method: 'POST' });
                const result = await response.json();
                
                if (response.ok) {
                    showNotification('Monitoring cycle triggered successfully', 'success');
                    setTimeout(refreshData, 2000); // Refresh after 2 seconds
                } else {
                    showNotification('Failed to trigger monitoring: ' + result.error, 'error');
                }
            } catch (error) {
                showNotification('Error triggering monitoring: ' + error.message, 'error');
            }
        }

        async function resolveAlert(alertId) {
            try {
                const response = await fetch(`/api/alerts/${alertId}/resolve`, { method: 'POST' });
                const result = await response.json();
                
                if (response.ok) {
                    showNotification('Alert resolved successfully', 'success');
                    refreshData();
                } else {
                    showNotification('Failed to resolve alert: ' + result.error, 'error');
                }
            } catch (error) {
                showNotification('Error resolving alert: ' + error.message, 'error');
            }
        }

        function viewSLAReport() {
            window.open('/api/sla?window=24', '_blank');
        }

        function exportData() {
            window.open('/api/health', '_blank');
        }

        function viewMetrics() {
            window.open('/metrics', '_blank');
        }

        // Global variable to store current alerts and selected alert
        let currentAlerts = [];
        let selectedAlertId = null;

        function viewAlertDetails(alertId) {
            selectedAlertId = alertId;
            
            // Find the alert in current alerts
            const alert = currentAlerts.find(a => a.id === alertId);
            if (!alert) {
                showNotification('Alert not found', 'error');
                return;
            }
            
            // Populate modal with alert details
            populateAlertDetailsModal(alert);
            
            // Show modal
            document.getElementById('alert-details-modal').classList.add('show');
        }

        function populateAlertDetailsModal(alert) {
            const content = document.getElementById('alert-details-content');
            
            // Format timestamps
            const formatDate = (dateStr) => new Date(dateStr).toLocaleString();
            const formatDuration = (first, last) => {
                const firstTime = new Date(first);
                const lastTime = new Date(last);
                const diffMs = lastTime - firstTime;
                const hours = Math.floor(diffMs / (1000 * 60 * 60));
                const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
                if (hours > 0) return `${hours}h ${minutes}m`;
                return `${minutes}m`;
            };
            
            content.innerHTML = `
                <!-- Alert Overview -->
                <div class="alert-detail-section">
                    <h3>📋 Alert Overview</h3>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">Alert ID</span>
                            <span class="detail-value">${alert.id}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Severity</span>
                            <span class="detail-value ${alert.severity}">${alert.severity.toUpperCase()}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Endpoint</span>
                            <span class="detail-value">${alert.endpoint_name}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Status</span>
                            <span class="detail-value">${alert.resolved ? 'RESOLVED' : 'ACTIVE'}</span>
                        </div>
                    </div>
                </div>

                <!-- Alert Title & Description -->
                <div class="alert-detail-section">
                    <h3>📝 Alert Message</h3>
                    <div style="margin-bottom: 15px;">
                        <span class="detail-label">Title</span>
                        <div class="detail-value" style="font-size: 1.1em; margin-top: 5px;">${alert.title}</div>
                    </div>
                    <div class="alert-description">
                        ${alert.description}
                    </div>
                </div>

                <!-- Timing Information -->
                <div class="alert-detail-section">
                    <h3>⏰ Timing Information</h3>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">First Occurrence</span>
                            <span class="detail-value">${formatDate(alert.first_occurrence || alert.timestamp)}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Last Updated</span>
                            <span class="detail-value">${formatDate(alert.last_sent_timestamp || alert.timestamp)}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Duration</span>
                            <span class="detail-value">${alert.first_occurrence && alert.last_sent_timestamp ? 
                                formatDuration(alert.first_occurrence, alert.last_sent_timestamp) : 'N/A'}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Repeat Count</span>
                            <span class="detail-value">${alert.repeat_count || 0}</span>
                        </div>
                    </div>
                </div>

                ${alert.violation_details ? `
                <!-- SLO Violation Details -->
                <div class="alert-detail-section">
                    <h3>📊 SLO Violation Details</h3>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">Violation Type</span>
                            <span class="detail-value">${alert.violation_details.violation_type || 'N/A'}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Current Value</span>
                            <span class="detail-value">${alert.violation_details.current_value || 'N/A'}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Threshold Value</span>
                            <span class="detail-value">${alert.violation_details.threshold_value || 'N/A'}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Deviation</span>
                            <span class="detail-value ${alert.severity}">
                                ${alert.violation_details.current_value && alert.violation_details.threshold_value ? 
                                    (alert.violation_details.current_value - alert.violation_details.threshold_value).toFixed(2) : 'N/A'}
                            </span>
                        </div>
                    </div>
                </div>
                ` : ''}

                <!-- Technical Details -->
                <div class="alert-detail-section">
                    <h3>🔧 Technical Details</h3>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">Alert Type</span>
                            <span class="detail-value">${alert.alert_type || 'SLO Violation'}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Resolved</span>
                            <span class="detail-value ${alert.resolved ? 'success' : 'critical'}">
                                ${alert.resolved ? '✅ Yes' : '❌ No'}
                            </span>
                        </div>
                        ${alert.resolved_timestamp ? `
                        <div class="detail-item">
                            <span class="detail-label">Resolved At</span>
                            <span class="detail-value">${formatDate(alert.resolved_timestamp)}</span>
                        </div>
                        ` : ''}
                        ${alert.resolved_by ? `
                        <div class="detail-item">
                            <span class="detail-label">Resolved By</span>
                            <span class="detail-value">${alert.resolved_by}</span>
                        </div>
                        ` : ''}
                        ${alert.resolution_reason ? `
                        <div class="detail-item">
                            <span class="detail-label">Resolution Reason</span>
                            <span class="detail-value">${alert.resolution_reason}</span>
                        </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }

        function closeAlertDetailsModal() {
            document.getElementById('alert-details-modal').classList.remove('show');
            selectedAlertId = null;
        }

        async function resolveAlertFromModal() {
            if (!selectedAlertId) {
                showNotification('No alert selected', 'error');
                return;
            }
            
            try {
                const response = await fetch(`/api/alerts/${selectedAlertId}/resolve`, { method: 'POST' });
                const result = await response.json();
                
                if (response.ok) {
                    showNotification('Alert resolved successfully', 'success');
                    closeAlertDetailsModal();
                    refreshData();
                } else {
                    showNotification('Failed to resolve alert: ' + result.error, 'error');
                }
            } catch (error) {
                showNotification('Error resolving alert: ' + error.message, 'error');
            }
        }

        // Close modal when clicking outside
        document.addEventListener('click', function(event) {
            const modal = document.getElementById('alert-details-modal');
            if (event.target === modal) {
                closeAlertDetailsModal();
            }
        });

        // Close modal with Escape key
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeAlertDetailsModal();
            }
        });

        function showNotification(message, type) {
            const notification = document.getElementById('notification');
            notification.textContent = message;
            notification.className = `notification notification-${type} show`;
            
            setTimeout(() => {
                notification.classList.remove('show');
            }, 3000);
        }
    </script>
</body>
</html>
        """
    
    def run(self):
        """Run the dashboard server."""
        if self.running:
            return
        
        self.running = True
        port = self.config.reporting.dashboard_port
        
        # Check if port is available
        if not self._is_port_available(port):
            self.logger.warning(f"Port {port} is not available, trying alternative ports...")
            for alt_port in range(port + 1, port + 10):
                if self._is_port_available(alt_port):
                    port = alt_port
                    break
            else:
                self.logger.error("No available ports found for dashboard")
                return
        
        try:
            self.logger.info(f"Starting dashboard server on http://localhost:{port}")
            self.app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
        except Exception as e:
            self.logger.error(f"Dashboard server error: {e}")
        finally:
            self.running = False
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return True
        except OSError:
            return False
    
    def stop(self):
        """Stop the dashboard server."""
        self.running = False
        # Flask doesn't have a clean shutdown method, but the thread will stop when the main process exits


# Simplified dashboard for environments without Flask
class SimpleDashboard:
    """Simple text-based dashboard for monitoring system."""
    
    def __init__(self, config: Config, monitoring_service=None, alert_manager=None, data_manager=None):
        self.config = config
        self.monitoring_service = monitoring_service
        self.alert_manager = alert_manager
        self.data_manager = data_manager
        self.logger = logging.getLogger(__name__)
    
    def print_status(self):
        """Print current status to console."""
        try:
            if self.monitoring_service:
                health = self.monitoring_service.get_health_status()
                if health:
                    print("\n" + "="*60)
                    print("🚀 BrightEdge API Monitoring Dashboard")
                    print("="*60)
                    print(f"📊 Overall Health: {'✅ Healthy' if health.is_healthy() else '❌ Unhealthy'}")
                    print(f"📈 Overall Availability: {health.overall_availability:.2f}%")
                    print(f"⏱️  Avg Response Time: {health.overall_avg_response_time:.2f}ms")
                    print(f"🚨 Active Alerts: {health.active_alerts}")
                    
                    print("\n📊 Endpoint Status:")
                    print("-" * 60)
                    for name, status in health.endpoints_status.items():
                        health_icon = "✅" if status['healthy'] else "❌"
                        print(f"{health_icon} {name}")
                        print(f"    Availability: {status['availability_percentage']:.1f}%")
                        print(f"    Avg Response: {status['avg_response_time_ms']:.1f}ms")
            
            if self.alert_manager:
                alerts = self.alert_manager.get_active_alerts()
                if alerts:
                    print("\n🚨 Active Alerts:")
                    print("-" * 60)
                    for alert in alerts:
                        severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(alert.severity.value, "⚪")
                        print(f"{severity_icon} {alert.title}")
                        print(f"    {alert.description}")
                else:
                    print("\n✅ No active alerts")
            
            print("=" * 60)
            
        except Exception as e:
            self.logger.error(f"Error displaying dashboard: {e}")
    
    def run(self):
        """Run simple dashboard (just print status)."""
        self.print_status()
    
    def stop(self):
        """Stop simple dashboard (no-op)."""
        pass


# Factory function to create appropriate dashboard
def create_dashboard(config: Config, monitoring_service=None, alert_manager=None, data_manager=None):
    """Create appropriate dashboard based on available dependencies."""
    if FLASK_AVAILABLE:
        return DashboardServer(config, monitoring_service, alert_manager, data_manager)
    else:
        return SimpleDashboard(config, monitoring_service, alert_manager, data_manager) 