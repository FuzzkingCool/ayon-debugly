import os
from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.collectors import collector_env, collector_logs, collector_os, collector_system_spec, collector_user
from ayon_debugly.endpoints.endpoint_shared_dir import EndpointSharedDir
from ayon_debugly.endpoints.endpoint_notion import NotionEndpoint

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
            from ayon_debugly.collectors.collector_software_checks import CollectorSoftwareChecks
            self.collectors.append(CollectorSoftwareChecks())
        except ImportError:
            pass
        
        # Initialize endpoints based on settings
        self.endpoints = []
        
        # Always add shared directory endpoint as fallback
        self.endpoints.append(EndpointSharedDir(settings=settings))
        
        # Add Notion endpoint if enabled
        try:
            notion_endpoint = NotionEndpoint()
            notion_endpoint.initialize()
            self.endpoints.append(notion_endpoint)
        except Exception as e:
            # Notion endpoint not available or not configured
            pass

    def collect_data(self):
        data = {}
        for collector in self.collectors:
            data.update(collector.collect())
        return data

    def submit_report(self, title, user_message, attachments=None, screenshot=None):
        collected_data = self.collect_data()
        issue = DebuglyIssue(title, user_message, collected_data, attachments, screenshot)
        
        results = []
        for endpoint in self.endpoints:
            try:
                result = endpoint.submit(issue)
                results.append(result)
            except Exception as e:
                # Log error but continue with other endpoints
                print(f"Failed to submit to {endpoint.__class__.__name__}: {e}")
        
        return results

    def list_issues(self):
        """List all issues in the shared dir, returning their metadata."""
        issues = []
        # Use the first shared directory endpoint for listing
        shared_dir_endpoint = next((ep for ep in self.endpoints if isinstance(ep, EndpointSharedDir)), None)
        if shared_dir_endpoint:
            shared_dir = shared_dir_endpoint.shared_dir
            for fname in os.listdir(shared_dir):
                if fname.endswith(".zip"):
                    try:
                        zip_path = os.path.join(shared_dir, fname)
                        issue = DebuglyIssue.from_zip(zip_path)
                        issues.append(issue)
                    except Exception:
                        continue
        return issues
