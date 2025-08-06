import os

from ayon_debugly.collectors import (
    collector_env,
    collector_logs,
    collector_os,
    collector_system_spec,
    collector_user,
)
from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.endpoints.endpoint_notion import EndpointNotion
from ayon_debugly.endpoints.endpoint_shared_folder import EndpointSharedFolder
from ayon_debugly.logger import log


class DebuglyIssueManager:
    def __init__(self, settings=None):
        self.settings = settings
        self.collectors = [
            collector_env.CollectorEnv(),
            collector_logs.CollectorLogs(),
            collector_os.CollectorOS(),
            collector_system_spec.CollectorSystemSpec(),
            collector_user.CollectorUser(),
        ]
        # Add software checks collector if available
        try:
            from ayon_debugly.collectors.collector_software_checks import (
                CollectorSoftwareChecks,
            )
            self.collectors.append(CollectorSoftwareChecks())
        except ImportError:
            pass
        
        # Initialize endpoints based on settings
        self.endpoints = []
        
        # Add Shared Folder endpoint if enabled
        try:
            shared_folder_endpoint = EndpointSharedFolder(settings=settings)
            self.endpoints.append(shared_folder_endpoint)
            log.info("Shared Folder endpoint initialized successfully")
        except Exception as e:
            log.warning(f"Shared Folder endpoint not available: {e}")
        
        # Add Notion endpoint if enabled
        try:
            notion_endpoint = EndpointNotion()
            notion_endpoint.initialize(settings=settings)
            self.endpoints.append(notion_endpoint)
            log.info("Notion endpoint initialized successfully")
        except Exception as e:
            log.warning(f"Notion endpoint not available: {e}")
        
        # Check if we have any endpoints configured
        if not self.endpoints:
            log.error("WARNING: No endpoints are configured or enabled! Speak to your administrator.")
        else:
            log.info(f"Initialized {len(self.endpoints)} endpoint(s)")

    def collect_data(self):
        data = {}
        for collector in self.collectors:
            data.update(collector.collect())
        return data

    def submit_report(self, title, user_message, attachments=None, screenshot=None, log_files=None, collected_data=None):
        # Check if we have any endpoints configured
        if not self.endpoints:
            raise Exception("No endpoints are configured or enabled. Please check your settings.")
        
        # Use provided collected_data or collect it if not provided
        if collected_data is None:
            collected_data = self.collect_data()
        
        # Debug: Log the collected data before creating the issue
        log.debug(f"DebuglyIssueManager: Collected data keys: {list(collected_data.keys()) if collected_data else 'None'}")
        # Log collected data safely to avoid Unicode encoding issues
        try:
            log.debug(f"DebuglyIssueManager: Collected data keys: {list(collected_data.keys())}")
        except Exception as e:
            log.debug(f"DebuglyIssueManager: Could not log collected data content due to encoding: {e}")
        
        issue = DebuglyIssue(title, user_message, collected_data, attachments, screenshot, log_files)
        
        results = []
        endpoint_results = []  # Track endpoint and result pairs
        failed_endpoints = []
        
        try:
            for endpoint in self.endpoints:
                try:
                    result = endpoint.submit(issue)
                    results.append(result)
                    endpoint_results.append((endpoint, result))
                    log.info(f"Successfully submitted to {endpoint.__class__.__name__}")
                except Exception as e:
                    failed_endpoints.append(f"{endpoint.__class__.__name__}: {e}")
                    log.error(f"Failed to submit to {endpoint.__class__.__name__}: {e}")
            
            # If all endpoints failed, raise an exception
            if not results and failed_endpoints:
                error_msg = "Failed to submit to all endpoints:\n" + "\n".join(failed_endpoints)
                raise Exception(error_msg)
            
            # If some endpoints failed, log a warning but return successful results
            if failed_endpoints:
                log.warning(f"Some endpoints failed, but {len(results)} submissions succeeded")
            
            return endpoint_results
        finally:
            # Always cleanup temporary files
            try:
                issue.cleanup()
            except Exception as e:
                log.warning(f"Failed to cleanup issue temporary files: {e}")
            
            # Cleanup endpoint temporary files
            for endpoint in self.endpoints:
                try:
                    endpoint.cleanup_temp_files()
                except Exception as e:
                    log.warning(f"Failed to cleanup {endpoint.__class__.__name__} temporary files: {e}")

    def list_issues(self):
        """List all issues in the shared folder, returning their metadata."""
        issues = []
        # Use the first Shared Folder endpoint for listing
        shared_folder_endpoint = next((ep for ep in self.endpoints if isinstance(ep, EndpointSharedFolder)), None)
        if shared_folder_endpoint:
            shared_folder = shared_folder_endpoint.shared_folder
            for fname in os.listdir(shared_folder):
                if fname.endswith(".zip"):
                    try:
                        zip_path = os.path.join(shared_folder, fname)
                        issue = DebuglyIssue.from_zip(zip_path)
                        issues.append(issue)
                    except Exception:
                        continue
        return issues
