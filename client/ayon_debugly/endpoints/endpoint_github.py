from .endpoint_base import EndpointBase
import requests
import os

class GitHubEndpoint(EndpointBase):
    def initialize(self):
        self.token = os.environ["GITHUB_TOKEN"]
        self.repo = os.environ["GITHUB_REPO"]

    def submit(self, issue):
        url = f"https://api.github.com/repos/{self.repo}/issues"
        headers = {"Authorization": f"token {self.token}"}
        data = {
            "title": issue.user_message[:100],
            "body": issue.user_message + "\n\n" + str(issue.collected_data)
        }
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()["html_url"]
