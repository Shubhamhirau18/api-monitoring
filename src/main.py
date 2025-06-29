#!/usr/bin/env python3
"""
BrightEdge API Monitoring System - Main Application

This is the main entry point for the monitoring system that orchestrates
all components including monitoring, alerting, data storage, and reporting.
"""

import sys
import os
import time
import signal
import logging
import schedule
from datetime import datetime, timedelta
from typing import Dict, List
import threading
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config, Config
from monitor import MonitoringService
from alerting import AlertManager
from storage import DataManager
from models import HealthStatus
from dashboard import create_dashboard


class MonitoringApp:
    """Main monitoring application that orchestrates all components."""
    
    def __init__(self, config_path: str = "config/monitoring_config.yaml"):
        self.config_path = config_path
        self.config: Config = None
        self.monitoring_service: MonitoringService = None
        self.alert_manager: AlertManager = None
        self.data_manager: DataManager = None
        self.dashboard_server: DashboardServer = None
        
        self.running = False
        self.thread_pool = []
        
        # Setup logging
        self._setup_logging()
        self.logger = logging.getLogger(__name__)
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _setup_logging(self):
        """Setup logging configuration."""
        handlers = [logging.StreamHandler()]
        
        # Only add file handler if not in Kubernetes or explicitly enabled
        if os.getenv('KUBERNETES_SERVICE_HOST') is None and os.getenv('DISABLE_FILE_LOGGING') != 'true':
            try:
                # Try to create log file in /tmp if possible, otherwise skip
                log_path = os.getenv('LOG_FILE_PATH', '/tmp/monitoring.log')
                handlers.append(logging.FileHandler(log_path))
            except (OSError, PermissionError):
                # If we can't create log file, just use console logging
                pass
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.stop()
    
    def initialize(self) -> bool:
        """Initialize all components."""
        try:
            # Load configuration
            self.logger.info(f"Loading configuration from {self.config_path}")
            self.config = load_config(self.config_path)
            
            # Initialize components
            self.logger.info("Initializing monitoring service...")
            self.monitoring_service = MonitoringService(self.config)
            
            self.logger.info("Initializing alert manager...")
            self.alert_manager = AlertManager(self.config)
            
            self.logger.info("Initializing data manager...")
            self.data_manager = DataManager(self.config)
            
            # Test storage connection
            if not self.data_manager.test_connection():
                self.logger.warning("Storage backend connection test failed, but continuing...")
            
            # Test alert channels
            self.logger.info("Testing alert channels...")
            channel_results = self.alert_manager.test_all_channels()
            for channel, result in channel_results.items():
                status = "OK" if result else "FAILED"
                self.logger.info(f"Alert channel {channel}: {status}")
            
            # Initialize dashboard if configured
            if hasattr(self.config, 'reporting') and self.config.reporting:
                self.logger.info("Initializing dashboard server...")
                self.dashboard_server = create_dashboard(
                    self.config, 
                    self.monitoring_service, 
                    self.alert_manager,
                    self.data_manager
                )
            
            self.logger.info("All components initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize application: {e}")
            return False
    
    def run_monitoring_cycle(self):
        """Run a single monitoring cycle."""
        try:
            self.logger.debug("Starting monitoring cycle...")
            
            # Run monitoring checks (now includes outage detection)
            results = self.monitoring_service.run_monitoring_cycle()
            
            # Store results
            for result in results:
                self.data_manager.store_monitoring_result(result)
            
            # Store outage state metrics in Prometheus (BEFORE creating alerts)
            if hasattr(self.data_manager, 'storage') and hasattr(self.data_manager.storage, 'store_outage_state'):
                # Store outage state for each endpoint
                for endpoint in self.config.endpoints:
                    outage_state = self.monitoring_service.get_endpoint_outage_state(endpoint.name)
                    if outage_state:
                        self.data_manager.storage.store_outage_state(outage_state)
                
                # Store outage events BEFORE they get cleared by create_outage_alerts()
                outage_events = self.monitoring_service.get_outage_events()
                for event in outage_events:
                    self.data_manager.storage.store_outage_event(event)
            
            # Process outage alerts (after storing events)
            outage_alerts = self.monitoring_service.create_outage_alerts()
            if outage_alerts:
                for alert in outage_alerts:
                    self.data_manager.store_alert(alert)
                    # Send outage alerts immediately (bypass normal processing)
                    self.alert_manager.send_alert(alert)
                    
                    # If this is a recovery alert, auto-resolve any active outage alerts for this endpoint
                    if alert.alert_type == "outage_detection" and "RECOVERY" in alert.title:
                        self._auto_resolve_outage_alerts(alert.endpoint_name, "Service has recovered")
                
                self.logger.warning(f"Generated {len(outage_alerts)} outage alerts")
            
            # Calculate SLA metrics
            sla_metrics = self.monitoring_service.analyze_sla_compliance()
            for endpoint_name, metrics in sla_metrics.items():
                self.data_manager.store_sla_metrics(metrics)
            
            # Check for violations and generate alerts
            violations = self.monitoring_service.check_violations()
            if violations:
                alerts = self.alert_manager.process_violations(violations)
                for alert in alerts:
                    self.data_manager.store_alert(alert)
            
            # Check for auto-resolution of existing alerts when conditions improve
            resolved_alert_ids = self.alert_manager.process_auto_resolution(sla_metrics)
            if resolved_alert_ids:
                self.logger.info(f"Auto-resolved {len(resolved_alert_ids)} alerts due to improved conditions")
            
            # Log summary with outage information
            total_endpoints = len(self.config.endpoints)
            healthy_endpoints = sum(1 for r in results if r.is_success())
            current_outages = self.monitoring_service.get_current_outages()
            degraded_endpoints = self.monitoring_service.get_degraded_endpoints()
            
            log_message = f"Monitoring cycle completed: {healthy_endpoints}/{total_endpoints} endpoints healthy"
            if current_outages:
                log_message += f", {len(current_outages)} OUTAGES"
            if degraded_endpoints:
                log_message += f", {len(degraded_endpoints)} degraded"
            
            self.logger.info(log_message)
            
        except Exception as e:
            self.logger.error(f"Error in monitoring cycle: {e}")
    
    def start_dashboard(self):
        """Start the dashboard server in a separate thread."""
        if self.dashboard_server:
            def run_dashboard():
                try:
                    self.dashboard_server.run()
                except Exception as e:
                    self.logger.error(f"Dashboard server error: {e}")
            
            dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
            dashboard_thread.start()
            self.thread_pool.append(dashboard_thread)
            self.logger.info(f"Dashboard server started on port {self.config.reporting.dashboard_port}")
    
    def run(self, run_once: bool = False):
        """Run the monitoring application."""
        if not self.initialize():
            self.logger.error("Failed to initialize application")
            return False
        
        self.running = True
        
        if run_once:
            # Run once and exit
            self.logger.info("Running single monitoring cycle...")
            self.run_monitoring_cycle()
            return True
        
        # Schedule monitoring cycles
        schedule.every(self.config.monitoring.interval_seconds).seconds.do(self.run_monitoring_cycle)
        
        # Schedule recurring alert processing
        schedule.every(self.config.alerting.repeat_interval_minutes).minutes.do(self._process_recurring_alerts)
        
        # Schedule SLA reporting (every hour)
        schedule.every().hour.do(self._generate_sla_report)
        
        # Start dashboard server
        self.start_dashboard()
        
        self.logger.info(f"Starting continuous monitoring (interval: {self.config.monitoring.interval_seconds}s)")
        self.logger.info("Press Ctrl+C to stop")
        
        # Run initial monitoring cycle
        self.run_monitoring_cycle()
        
        # Main monitoring loop
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        finally:
            self.stop()
        
        return True
    
    def _process_recurring_alerts(self):
        """Process recurring alerts that need to be resent."""
        try:
            recurring_alerts = self.alert_manager.process_recurring_alerts()
            if recurring_alerts:
                self.logger.info(f"Processed {len(recurring_alerts)} recurring alerts")
                # Store recurring alerts
                for alert in recurring_alerts:
                    self.data_manager.store_alert(alert)
        except Exception as e:
            self.logger.error(f"Error processing recurring alerts: {e}")
    
    def _auto_resolve_outage_alerts(self, endpoint_name: str, reason: str):
        """Auto-resolve any active outage alerts for an endpoint when it recovers."""
        try:
            active_alerts = self.alert_manager.get_active_alerts()
            resolved_count = 0
            
            for alert in active_alerts:
                if (alert.endpoint_name == endpoint_name and 
                    alert.alert_type == "outage_detection" and
                    "OUTAGE" in alert.title):  # Only resolve outage alerts, not recovery alerts
                    
                    if self.alert_manager.resolve_alert(alert.id, auto_resolved=True, reason=reason):
                        resolved_count += 1
                        self.logger.info(f"Auto-resolved outage alert {alert.id} for {endpoint_name}")
            
            if resolved_count > 0:
                self.logger.info(f"Auto-resolved {resolved_count} outage alerts for {endpoint_name}")
                
        except Exception as e:
            self.logger.error(f"Error auto-resolving outage alerts for {endpoint_name}: {e}")
    
    def _generate_sla_report(self):
        """Generate and log SLA compliance report."""
        try:
            health_status = self.monitoring_service.get_health_status()
            
            self.logger.info("=== SLA COMPLIANCE REPORT ===")
            self.logger.info(f"Overall Health: {'HEALTHY' if health_status.is_healthy() else 'UNHEALTHY'}")
            self.logger.info(f"Overall Availability: {health_status.overall_availability:.2f}%")
            self.logger.info(f"Overall Avg Response Time: {health_status.overall_avg_response_time:.2f}ms")
            self.logger.info(f"Active Alerts: {health_status.active_alerts}")
            
            for endpoint_name, status in health_status.endpoints_status.items():
                health_icon = "✅" if status['healthy'] else "❌"
                self.logger.info(
                    f"{health_icon} {endpoint_name}: "
                    f"Availability {status['availability_percentage']:.1f}%, "
                    f"Avg Response {status['avg_response_time_ms']:.1f}ms"
                )
            
            self.logger.info("=============================")
            
        except Exception as e:
            self.logger.error(f"Error generating SLA report: {e}")
    
    def stop(self):
        """Stop the monitoring application gracefully."""
        self.logger.info("Stopping monitoring application...")
        self.running = False
        
        # Stop dashboard server
        if self.dashboard_server:
            self.dashboard_server.stop()
        
        # Wait for threads to complete
        for thread in self.thread_pool:
            if thread.is_alive():
                thread.join(timeout=5)
        
        self.logger.info("Application stopped")
    
    def get_health_status(self) -> HealthStatus:
        """Get current health status."""
        if self.monitoring_service:
            return self.monitoring_service.get_health_status()
        return None
    
    def get_active_alerts(self) -> List:
        """Get currently active alerts."""
        if self.alert_manager:
            return self.alert_manager.get_active_alerts()
        return []


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='BrightEdge API Monitoring System')
    parser.add_argument(
        '--config', '-c',
        default='config/monitoring_config.yaml',
        help='Configuration file path'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run monitoring once and exit'
    )
    parser.add_argument(
        '--test-config',
        action='store_true',
        help='Test configuration and exit'
    )
    parser.add_argument(
        '--test-alerts',
        action='store_true',
        help='Test alert channels and exit'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    app = MonitoringApp(args.config)
    
    # Test configuration
    if args.test_config:
        print("Testing configuration...")
        if app.initialize():
            print("✅ Configuration is valid")
            health = app.get_health_status()
            if health:
                print(f"📊 {health.total_endpoints} endpoints configured")
            return 0
        else:
            print("❌ Configuration is invalid")
            return 1
    
    # Test alert channels
    if args.test_alerts:
        print("Testing alert channels...")
        if app.initialize():
            results = app.alert_manager.test_all_channels()
            for channel, result in results.items():
                status = "✅ OK" if result else "❌ FAILED"
                print(f"{channel}: {status}")
            return 0 if all(results.values()) else 1
        else:
            print("❌ Failed to initialize application")
            return 1
    
    # Run monitoring
    try:
        success = app.run(run_once=args.once)
        return 0 if success else 1
    except Exception as e:
        print(f"❌ Application error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 