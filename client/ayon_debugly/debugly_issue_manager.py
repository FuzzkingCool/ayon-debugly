import os
from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.collectors import collector_env, collector_logs, collector_os, collector_system_spec, collector_user
from ayon_debugly.endpoints.endpoint_shared_dir import EndpointSharedDir

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
        self.endpoint = EndpointSharedDir(settings=settings)

    def collect_data(self):
        data = {}
        for collector in self.collectors:
            data.update(collector.collect())
        return data

    def submit_report(self, title, user_message, attachments=None, screenshot=None):
        collected_data = self.collect_data()
        issue = DebuglyIssue(title, user_message, collected_data, attachments, screenshot)
        return self.endpoint.submit(issue)

    def list_issues(self):
        """List all issues in the shared dir, returning their metadata."""
        issues = []
        shared_dir = self.endpoint.shared_dir
        for fname in os.listdir(shared_dir):
            if fname.endswith(".zip"):
                try:
                    zip_path = os.path.join(shared_dir, fname)
                    issue = DebuglyIssue.from_zip(zip_path)
                    issues.append(issue)
                except Exception:
                    continue
        return issues
