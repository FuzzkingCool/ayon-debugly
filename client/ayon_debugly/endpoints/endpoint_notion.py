# https://www.notion.so/21e2a1fa30c08032b940d622c10de9be?v=21e2a1fa30c08126817e000ce02a47f7&source=copy_link

import os
import requests
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from ayon_debugly.endpoints.endpoint_base import EndpointBase
from ayon_debugly.debugly_issue import DebuglyIssue

class NotionEndpoint(EndpointBase):
    def __init__(self):
        self.notion_token = None
        self.database_id = None
        self.notion_version = "2022-06-28"
        self.base_url = "https://api.notion.com/v1"
        super().__init__()

    def initialize(self):
        """Initialize the Notion endpoint with required credentials and database ID"""
        from ayon_core.settings import get_system_settings
        
        settings = get_system_settings()
        notion_settings = settings.get("ayon_debugly", {}).get("endpoints", {}).get("notion", {})
        
        if not notion_settings.get("enabled", False):
            raise ValueError("Notion endpoint is not enabled in settings")
        
        notion_config = notion_settings.get("notion", {})
        self.notion_token = notion_config.get("api_key")
        self.database_id = notion_config.get("database_id")
        self.assignee_id = notion_config.get("assignee_id", "")
        
        if not self.notion_token:
            raise ValueError("Notion API key is required in settings")
        if not self.database_id:
            raise ValueError("Notion database ID is required in settings")

    def submit(self, issue: DebuglyIssue) -> str:
        """
        Submit an issue to the Notion database
        
        Args:
            issue: DebuglyIssue object containing all issue data
            
        Returns:
            str: URL of the created Notion page
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }

        # Prepare the page properties based on the database schema
        properties = self._build_properties(issue)
        
        # Prepare the page content (blocks)
        children = self._build_content_blocks(issue)
        
        data = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
            "children": children
        }

        response = requests.post(
            f"{self.base_url}/pages",
            headers=headers,
            json=data
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to create Notion page: {response.status_code} - {response.text}")
        
        result = response.json()
        return result.get("url", "")

    def _build_properties(self, issue: DebuglyIssue) -> Dict[str, Any]:
        """
        Build the properties object for the Notion page based on the database schema
        
        Args:
            issue: DebuglyIssue object
            
        Returns:
            Dict containing the page properties
        """
        properties = {}
        
        # Title (required field)
        properties["Title"] = {
            "title": [
                {
                    "type": "text",
                    "text": {
                        "content": issue.title[:2000]  # Notion title limit
                    }
                }
            ]
        }
        
        # Tags (multi-select)
        if hasattr(issue, 'tags') and issue.tags:
            properties["Tags"] = {
                "multi_select": [
                    {"name": tag.strip()} for tag in issue.tags if tag.strip()
                ]
            }
        
        # Short Description (rich_text)
        if issue.user_message:
            properties["Short Description"] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": issue.user_message[:2000]  # Notion text limit
                        }
                    }
                ]
            }
        
        # Status (select) - default to "Open" or "New"
        properties["Status"] = {
            "select": {
                "name": "Open"
            }
        }
        
        # Priority (select) - default to "Medium"
        properties["Priority"] = {
            "select": {
                "name": "Medium"
            }
        }
        
        # Assign (people) - can be set via settings
        if self.assignee_id:
            properties["Assign"] = {
                "people": [
                    {"id": self.assignee_id}
                ]
            }
        
        # Created Time (date) - will be automatically set by Notion
        
        return properties

    def _build_content_blocks(self, issue: DebuglyIssue) -> List[Dict[str, Any]]:
        """
        Build the content blocks for the Notion page
        
        Args:
            issue: DebuglyIssue object
            
        Returns:
            List of block objects
        """
        blocks = []
        
        # Add detailed description
        if issue.user_message:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "## Issue Description"
                            },
                            "annotations": {
                                "bold": True,
                                "italic": False,
                                "strikethrough": False,
                                "underline": False,
                                "code": False,
                                "color": "default"
                            }
                        }
                    ]
                }
            })
            
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": issue.user_message
                            }
                        }
                    ]
                }
            })
        
        # Add collected data
        if issue.collected_data:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "## Collected Data"
                            },
                            "annotations": {
                                "bold": True,
                                "italic": False,
                                "strikethrough": False,
                                "underline": False,
                                "code": False,
                                "color": "default"
                            }
                        }
                    ]
                }
            })
            
            # Add collected data as code block
            collected_data_str = json.dumps(issue.collected_data, indent=2)
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": collected_data_str
                            }
                        }
                    ],
                    "language": "json"
                }
            })
        
        # Add attachments section if there are any
        all_attachments = []
        if issue.attachments:
            all_attachments.extend(issue.attachments)
        if issue.screenshot:
            all_attachments.append(issue.screenshot)
        if issue.log_files:
            all_attachments.extend(issue.log_files)
        
        if all_attachments:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "## Attachments"
                            },
                            "annotations": {
                                "bold": True,
                                "italic": False,
                                "strikethrough": False,
                                "underline": False,
                                "code": False,
                                "color": "default"
                            }
                        }
                    ]
                }
            })
            
            # Note: Notion file uploads require a separate API call
            # For now, we'll add a note about attachments
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"Number of attachments: {len(all_attachments)}"
                            }
                        }
                    ]
                }
            })
        
        # Add timestamp
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"## Timestamp\nCreated: {issue.timestamp}"
                        }
                    }
                ]
            }
        })
        
        return blocks

    def upload_file(self, file_path: str, page_id: str) -> str:
        """
        Upload a file to a Notion page
        
        Args:
            file_path: Path to the file to upload
            page_id: ID of the Notion page to attach the file to
            
        Returns:
            str: URL of the uploaded file
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # First, create a file upload
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }
        
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        upload_data = {
            "filename": file_name,
            "size": file_size
        }
        
        response = requests.post(
            f"{self.base_url}/files",
            headers=headers,
            json=upload_data
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to create file upload: {response.status_code} - {response.text}")
        
        upload_info = response.json()
        upload_url = upload_info["upload_url"]
        
        # Upload the file content
        with open(file_path, 'rb') as f:
            file_response = requests.put(upload_url, data=f)
            
        if file_response.status_code != 200:
            raise Exception(f"Failed to upload file content: {file_response.status_code}")
        
        # Complete the upload
        complete_data = {
            "s3_signed_urls": {
                upload_info["s3_signed_urls"]["name"]: upload_url
            }
        }
        
        complete_response = requests.patch(
            f"{self.base_url}/files/{upload_info['id']}",
            headers=headers,
            json=complete_data
        )
        
        if complete_response.status_code != 200:
            raise Exception(f"Failed to complete file upload: {complete_response.status_code}")
        
        return upload_info["url"]