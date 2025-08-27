# -*- coding: utf-8 -*-
import json
import os
from typing import Any, Dict, List

import requests

from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.endpoints.endpoint_base import EndpointBase
from ayon_debugly.logger import log


class EndpointNotion(EndpointBase):
    def __init__(self):
        self.notion_token = None
        self.database_id = None
        self.notion_version = "2022-06-28"  # Latest stable version - try "2022-02-22" if this fails
        self.base_url = "https://api.notion.com/v1"
        super().__init__()

    def initialize(self, settings=None):
        """Initialize the Notion endpoint with required credentials and database ID"""
        import ayon_api

        from ayon_debugly.version import __version__
        
        try:
            # Use provided settings or fetch from API
            if settings is None:
                settings = ayon_api.get_addon_settings("debugly", __version__)
            log.debug(f"Notion endpoint: Loaded settings type: {type(settings)}")
            log.debug(f"Notion endpoint: Settings keys: {list(settings.keys()) if isinstance(settings, dict) else 'Not a dict'}")
            
            # Debug: Log the full settings structure for notion
            if isinstance(settings, dict) and "endpoints" in settings:
                log.debug(f"Notion endpoint: Full endpoints structure: {settings['endpoints']}")
                if "notion" in settings["endpoints"]:
                    log.debug(f"Notion endpoint: Full notion structure: {settings['endpoints']['notion']}")
                    if "notion" in settings["endpoints"]["notion"]:
                        log.debug(f"Notion endpoint: Full notion config: {settings['endpoints']['notion']['notion']}")
                        # Check each field individually
                        notion_config = settings['endpoints']['notion']['notion']
                        log.debug(f"Notion endpoint: database_id from direct access: '{notion_config.get('database_id', 'NOT_FOUND')}'")
                        log.debug(f"Notion endpoint: api_key from direct access: '{notion_config.get('api_key', 'NOT_FOUND')}'")
                        log.debug(f"Notion endpoint: assignee_id from direct access: '{notion_config.get('assignee_id', 'NOT_FOUND')}'")
                        log.debug(f"Notion endpoint: All keys in notion config: {list(notion_config.keys())}")
                        log.debug(f"Notion endpoint: All values in notion config: {list(notion_config.values())}")
            
            # Handle multiple possible settings structures
            notion_settings = None
            notion_config = None
            
            # Try endpoints.notion structure first
            if hasattr(settings, "endpoints") and hasattr(settings.endpoints, "notion"):
                notion_settings = settings.endpoints.notion
                if notion_settings.enabled:
                    notion_config = notion_settings.notion
            elif isinstance(settings, dict):
                # Try endpoints.notion structure
                if "endpoints" in settings and "notion" in settings["endpoints"]:
                    notion_settings = settings["endpoints"]["notion"]
                    if notion_settings.get("enabled", False):
                        notion_config = notion_settings.get("notion", {})
                # Try direct notion structure (as provided by user)
                elif "notion" in settings:
                    notion_settings = settings["notion"]
                    if notion_settings.get("enabled", False):
                        notion_config = notion_settings.get("notion", {})
            
            if not notion_settings or not notion_config:
                raise ValueError("Notion endpoint configuration not found in settings")
            
            # Extract configuration values
            if hasattr(notion_config, "api_key"):
                api_key_secret = notion_config.api_key
                self.database_id = notion_config.database_id
                self.assignee_id = getattr(notion_config, "assignee_id", "") or ""
            else:
                api_key_secret = notion_config.get("api_key")
                self.database_id = notion_config.get("database_id")
                self.assignee_id = notion_config.get("assignee_id", "")
            
            log.debug(f"Notion endpoint: Extracted database_id: '{self.database_id}'")
            log.debug(f"Notion endpoint: Extracted api_key_secret: '{api_key_secret}'")
            log.debug(f"Notion endpoint: Extracted assignee_id: '{self.assignee_id}'")
            log.debug(f"Notion endpoint: Database ID type: {type(self.database_id)}")
            log.debug(f"Notion endpoint: Database ID length: {len(self.database_id) if self.database_id else 0}")
            
            # Get the actual API key from the secret
            if api_key_secret:
                try:
                    secret_data = ayon_api.get_secret(api_key_secret)
                    self.notion_token = secret_data.get("value")
                except Exception as e:
                    raise ValueError(f"Failed to retrieve Notion API key from secret '{api_key_secret}': {e}")
            else:
                raise ValueError("Notion API key secret name is required in settings")
                
            if not self.notion_token:
                raise ValueError("Notion API key is required in settings")
            if not self.database_id:
                raise ValueError("Notion database ID is required in settings")
            
            # Clean the database ID (remove query parameters if present)
            if "?" in self.database_id:
                self.database_id = self.database_id.split("?")[0]
            
            # Ensure database ID has proper format (add dashes if missing)
            log.debug(f"Notion endpoint: Original database ID: {self.database_id}")
            if len(self.database_id) == 32 and "-" not in self.database_id:
                # Convert from compact format to UUID format
                self.database_id = f"{self.database_id[:8]}-{self.database_id[8:12]}-{self.database_id[12:16]}-{self.database_id[16:20]}-{self.database_id[20:]}"
                log.debug(f"Notion endpoint: Converted database ID to UUID format: {self.database_id}")
            else:
                log.debug(f"Notion endpoint: Database ID format check - length: {len(self.database_id)}, contains dashes: {'-' in self.database_id}")
            
            log.debug(f"Notion endpoint: Initialized with database_id: {self.database_id[:20]}...")
            log.debug(f"Notion endpoint: API key retrieved successfully: {bool(self.notion_token)}")
            
            # Validate database schema (optional)
            try:
                self._validate_database_schema()
            except Exception as e:
                log.warning(f"Notion endpoint: Database validation failed, continuing anyway: {e}")
                
        except Exception as e:
            log.error(f"Notion endpoint initialization failed: {e}")
            raise ValueError(f"Failed to initialize Notion endpoint: {e}")

    def submit(self, issue: DebuglyIssue) -> str:
        """
        Submit an issue to the Notion database
        
        Args:
            issue: DebuglyIssue object containing all issue data
            
        Returns:
            str: URL of the created Notion page
        """
        log.debug(f"Notion endpoint: Submitting issue '{issue.title}'")
        
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
            "children": children,
            "icon": {
                "type": "emoji",
                "emoji": "❓"
            }
        }

        log.debug(f"Notion endpoint: Request data keys: {list(data.keys())}")
        log.debug(f"Notion endpoint: Properties keys: {list(properties.keys())}")
        log.debug(f"Notion endpoint: Number of content blocks: {len(children)}")
        log.debug(f"Notion endpoint: Sending request to {self.base_url}/pages")
        log.debug(f"Notion endpoint: Database ID: {self.database_id}")
        log.debug(f"Notion endpoint: Token available: {bool(self.notion_token)}")
        log.debug(f"Notion endpoint: Full request data: {json.dumps(data, indent=2)}")
        log.debug(f"Notion endpoint: Content blocks types: {[block.get('type', 'unknown') for block in children]}")
        
        try:
            response = requests.post(
                f"{self.base_url}/pages",
                headers=headers,
                json=data,
                timeout=30  # Add timeout
            )
            log.debug(f"Notion endpoint: Response status: {response.status_code}")
            
            if response.status_code != 200:
                log.error(f"Notion endpoint: Failed to create page - {response.status_code}: {response.text}")
                log.error(f"Notion endpoint: Request data: {json.dumps(data, indent=2)}")
                log.error(f"Notion endpoint: Response headers: {dict(response.headers)}")
                try:
                    error_json = response.json()
                    log.error(f"Notion endpoint: Error response JSON: {json.dumps(error_json, indent=2)}")
                except:
                    log.error("Notion endpoint: Could not parse error response as JSON")
                raise Exception(f"Failed to create Notion page: {response.status_code} - {response.text}")
            else:
                log.debug(f"Notion endpoint: Page creation successful with status {response.status_code}")
        except requests.exceptions.RequestException as e:
            log.error(f"Notion endpoint: Request failed with exception: {e}")
            raise Exception(f"Notion API request failed: {e}")
        
        result = response.json()
        page_url = result.get("url", "")
        page_id = result.get("id", "")
        log.debug(f"Notion endpoint: Successfully created page: {page_url}")
        log.debug(f"Notion endpoint: Page ID: {page_id}")
        log.debug(f"Notion endpoint: Full API response: {json.dumps(result, indent=2)}")
        
        # Check if the Submitted By field was actually set in the response
        if "properties" in result:
            submitted_by_prop = result["properties"].get("Submitted By", {})
            log.debug(f"Notion endpoint: Submitted By field in API response: {submitted_by_prop}")
            
            # Check if the people array is empty or missing
            if submitted_by_prop and "people" in submitted_by_prop:
                people_array = submitted_by_prop["people"]
                log.debug(f"Notion endpoint: People array in response: {people_array}")
                if people_array:
                    log.debug(f"Notion endpoint: First person in array: {people_array[0]}")
                else:
                    log.warning("Notion endpoint: People array is empty in API response")
            else:
                log.warning("Notion endpoint: No people array found in Submitted By field")
        else:
            log.debug("Notion endpoint: No properties found in API response")
        
        # Upload attachments after page creation
        if page_id:
            self._upload_attachments_to_page(issue, page_id)
        
        return {"url": page_url, "page_id": page_id}

    def _build_properties(self, issue: DebuglyIssue) -> Dict[str, Any]:
        """
        Build the properties object for the Notion page based on the database schema
        
        Args:
            issue: DebuglyIssue object
            
        Returns:
            Dict containing the page properties
        """
        properties = {}
        
        # Use cached database properties if available, otherwise fetch them
        if not hasattr(self, '_database_properties'):
            headers = {
                "Authorization": f"Bearer {self.notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": self.notion_version
            }
            
            try:
                response = requests.get(
                    f"{self.base_url}/databases/{self.database_id}",
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code != 200:
                    log.warning("Notion endpoint: Could not retrieve database schema, using default properties")
                    self._database_properties = {}
                else:
                    database_info = response.json()
                    self._database_properties = database_info.get("properties", {})
            except Exception as e:
                log.warning(f"Notion endpoint: Could not retrieve database schema: {e}, using default properties")
                self._database_properties = {}
        
        database_properties = self._database_properties
        
        log.debug(f"Notion endpoint: Building properties with database properties: {list(database_properties.keys()) if database_properties else 'None'}")
        
        # Log the full database schema for debugging
        log.debug(f"Notion endpoint: Full database schema: {database_properties}")
        
        # Title (required field) - always include
        if "Title" in database_properties:
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
        else:
            # Fallback to Name if Title doesn't exist
            if "Name" in database_properties:
                properties["Name"] = {
                    "title": [
                        {
                            "type": "text",
                            "text": {
                                "content": issue.title[:2000]
                            }
                        }
                    ]
                }
            else:
                # If neither Title nor Name exists, use the first title property
                title_props = [k for k, v in database_properties.items() if v.get("type") == "title"]
                if title_props:
                    properties[title_props[0]] = {
                        "title": [
                            {
                                "type": "text",
                                "text": {
                                    "content": issue.title[:2000]
                                }
                            }
                        ]
                    }
                else:
                    # If no title property found, log warning and use a default
                    log.warning("Notion endpoint: No title property found in database, using 'Title' as fallback")
                    properties["Title"] = {
                        "title": [
                            {
                                "type": "text",
                                "text": {
                                    "content": issue.title[:2000]
                                }
                            }
                        ]
                    }
        
        # Tags (multi-select)
        if "Tags" in database_properties and hasattr(issue, 'tags') and issue.tags:
            properties["Tags"] = {
                "multi_select": [
                    {"name": tag.strip()} for tag in issue.tags if tag.strip()
                ]
            }
        
        # Short Description (rich_text) - Skip this field as it's not needed
        # if "Short Description" in database_properties and issue.user_message:
        #     properties["Short Description"] = {
        #         "rich_text": [
        #             {
        #                 "type": "text",
        #                 "text": {
        #                     "content": issue.user_message[:2000]  # Notion text limit
        #                 }
        #             }
        #         ]
        #     }
        
        # Status (select) - try to find a valid status option
        if "Status" in database_properties:
            status_prop = database_properties["Status"]
            if status_prop.get("type") == "select":
                # Get available options from the database schema
                status_options = status_prop.get("select", {}).get("options", [])
                if status_options:
                    # Try to find "Not started" as the default status
                    default_status = None
                    for option in status_options:
                        option_name = option.get("name", "")
                        if option_name == "Not started":
                            default_status = option["name"]
                            break
                    
                    # If no suitable status found, use the first available option
                    if not default_status and status_options:
                        default_status = status_options[0]["name"]
                    
                    if default_status:
                        properties["Status"] = {
                            "select": {
                                "name": default_status
                            }
                        }
                        log.debug(f"Notion endpoint: Using status: {default_status}")
                    else:
                        log.warning("Notion endpoint: No valid status options found, skipping Status property")
                else:
                    log.warning("Notion endpoint: Status property has no options defined, skipping Status property")
            else:
                log.warning(f"Notion endpoint: Status property is not a select type (found: {status_prop.get('type')}), skipping Status property")
        else:
            log.debug("Notion endpoint: Status property not found in database schema, skipping Status property")
        
        # Priority (select) - try to find a valid priority option
        if "Priority" in database_properties:
            priority_prop = database_properties["Priority"]
            if priority_prop.get("type") == "select":
                # Get available options from the database schema
                priority_options = priority_prop.get("select", {}).get("options", [])
                if priority_options:
                    # Try to find a suitable default priority
                    default_priority = None
                    for option in priority_options:
                        option_name = option.get("name", "").lower()
                        if any(keyword in option_name for keyword in ["P0", "P1", "P2", "P3"]):
                            default_priority = option["name"]
                            break
                    
                    # If no suitable priority found, use the first available option
                    if not default_priority and priority_options:
                        default_priority = priority_options[0]["name"]
                    
                    if default_priority:
                        properties["Priority"] = {
                            "select": {
                                "name": default_priority
                            }
                        }
                        log.debug(f"Notion endpoint: Using priority: {default_priority}")
                    else:
                        log.warning("Notion endpoint: No valid priority options found, skipping Priority property")
                else:
                    log.warning("Notion endpoint: Priority property has no options defined, skipping Priority property")
            else:
                log.warning(f"Notion endpoint: Priority property is not a select type (found: {priority_prop.get('type')}), skipping Priority property")
        else:
            log.debug("Notion endpoint: Priority property not found in database schema, skipping Priority property")
        
        # Assign (people) - can be set via settings
        if "Assign" in database_properties and self.assignee_id:
            properties["Assign"] = {
                "people": [
                    {"id": self.assignee_id}
                ]
            }
        
        # Submitted By (people) - set to the current user's Ayon full name
        if "Submitted By" in database_properties:
            log.debug("Notion endpoint: Processing Submitted By field")
            log.debug(f"Notion endpoint: Submitted By field schema: {database_properties['Submitted By']}")
        else:
            # Check for similar field names
            similar_fields = [key for key in database_properties.keys() if 'submitted' in key.lower() or 'by' in key.lower()]
            log.debug(f"Notion endpoint: Submitted By field not found. Similar fields: {similar_fields}")
            log.debug(f"Notion endpoint: All database properties: {list(database_properties.keys())}")
        
        if "Submitted By" in database_properties:
            
            # First, list all users in the workspace for debugging
            log.debug("Notion endpoint: Listing all users in workspace...")
            all_users = self._list_all_users()
            
            # Log all available users for debugging
            if all_users:
                log.debug(f"Notion endpoint: Found {len(all_users)} users in workspace:")
                for i, user in enumerate(all_users):
                    user_id = user.get("id", "No ID")
                    user_name = user.get("name", "No name")
                    user_type = user.get("type", "No type")
                    user_email = user.get("person", {}).get("email", "No email")
                    log.debug(f"Notion endpoint: User {i+1}: ID='{user_id}', Name='{user_name}', Type='{user_type}', Email='{user_email}'")
            else:
                log.warning("Notion endpoint: No users found in workspace")
            
            # Get user's Ayon full name from collected data
            user_full_name = None
            user_email = None
            user_username = None
            
            if hasattr(issue, 'collected_data') and issue.collected_data:
                # Try to find user data with case-insensitive search
                user_data = None
                for key in issue.collected_data.keys():
                    if key.lower() == 'user':
                        user_data = issue.collected_data[key]
                        break
                
                if not user_data:
                    log.debug(f"Notion endpoint: No user data found in collected_data. Available keys: {list(issue.collected_data.keys())}")
                    user_data = {}
                else:
                    log.debug(f"Notion endpoint: User data from collected_data: {user_data}")
                
                # The user data is nested - extract from the inner 'user' key
                if isinstance(user_data, dict) and 'user' in user_data:
                    user_data = user_data['user']
                    log.debug(f"Notion endpoint: Extracted nested user data: {user_data}")
                
                user_full_name = user_data.get('ayon_full_name')
                user_email = user_data.get('ayon_email')
                user_username = user_data.get('ayon_username')
                
                log.debug(f"Notion endpoint: Extracted user info - Full Name: '{user_full_name}', Email: '{user_email}', Username: '{user_username}'")
            else:
                log.debug("Notion endpoint: No collected_data found in issue")
            
            # Use email directly - it's unique and we have it
            if user_email and user_email != "unknown":
                log.debug(f"Notion endpoint: Searching for user by email: '{user_email}'")
                
                # Search in the workspace users list directly instead of using the search API
                user_id = None
                for user in all_users:
                    user_email_in_workspace = user.get("person", {}).get("email", "")
                    if user_email_in_workspace == user_email:
                        user_id = user.get("id")
                        log.debug(f"Notion endpoint: Found user by email '{user_email}' with ID: {user_id}")
                        break
                
                if not user_id:
                    log.warning(f"Notion endpoint: User with email '{user_email}' not found in Notion workspace")
            else:
                log.warning("Notion endpoint: No valid email found in user data")
                user_id = None
            
            if user_id:
                # Get the full user object from the search results
                user_object = None
                for user in all_users:
                    if user.get("id") == user_id:
                        user_object = user
                        break
                
                # Try the canonical Notion API approach for people fields
                # According to the API docs, we should use just the ID
                submitted_by_value = {
                    "people": [
                        {"id": user_id}
                    ]
                }
                properties["Submitted By"] = submitted_by_value
                log.debug(f"Notion endpoint: Set Submitted By to user: {user_email} (ID: {user_id})")
                log.debug(f"Notion endpoint: Submitted By property value: {submitted_by_value}")
                log.debug(f"Notion endpoint: User details - Name: '{user_email}', ID: '{user_id}'")
                
                # Also log the full user object for debugging
                if user_object:
                    log.debug(f"Notion endpoint: Full user object: {user_object}")
                    
                    # Try alternative format as backup (some integrations require full object)
                    alternative_value = {
                        "people": [
                            {
                                "object": "user",
                                "id": user_id,
                                "type": "person",
                                "name": user_object.get("name", user_email)
                            }
                        ]
                    }
                    log.debug(f"Notion endpoint: Alternative Submitted By value: {alternative_value}")
            else:
                log.warning(f"Notion endpoint: Could not find user with email '{user_email}' in Notion workspace")
                log.debug(f"Notion endpoint: Available users in workspace: {all_users}")
        else:
            log.debug("Notion endpoint: Submitted By field not found in database schema")
        
        # Attachments (files) - we'll handle this after page creation
        if "Attachments" in database_properties:
            log.debug("Notion endpoint: Attachments field found in database schema")
        else:
            log.debug("Notion endpoint: Attachments field not found in database schema")
        
        # Created Time (date) - will be automatically set by Notion
        
        log.debug(f"Notion endpoint: Final properties: {properties}")
        
        # Log each property being set for debugging
        for prop_name, prop_value in properties.items():
            log.debug(f"Notion endpoint: Setting property '{prop_name}': {prop_value}")
        
        # Specifically log the Submitted By property if it exists
        if "Submitted By" in properties:
            log.debug(f"Notion endpoint: Submitted By property is set to: {properties['Submitted By']}")
        else:
            log.debug("Notion endpoint: Submitted By property is NOT set in final properties")
        
        return properties

    def _clean_user_message(self, message: str) -> str:
        """
        Clean the user message to remove CSS and other unwanted content
        
        Args:
            message: Raw user message
            
        Returns:
            Cleaned message
        """
        if not message:
            return message
        
        # Remove CSS blocks
        import re
        
        # Remove CSS blocks that start with p, li { and end with }
        css_pattern = r'p,\s*li\s*\{[^}]*\}\s*hr\s*\{[^}]*\}\s*li\.unchecked::marker\s*\{[^}]*\}\s*li\.checked::marker\s*\{[^}]*\}'
        cleaned = re.sub(css_pattern, '', message, flags=re.DOTALL)
        
        # Remove any remaining CSS-like content
        css_like_pattern = r'[a-z-]+\s*\{[^}]*\}'
        cleaned = re.sub(css_like_pattern, '', cleaned, flags=re.DOTALL)
        
        # Clean up extra whitespace
        cleaned = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned)  # Remove excessive line breaks
        cleaned = cleaned.strip()
        
        log.debug(f"Notion endpoint: Cleaned message from {len(message)} to {len(cleaned)} characters")
        
        return cleaned

    def _parse_markdown_to_rich_text(self, markdown_text: str) -> List[Dict[str, Any]]:
        """
        Parse markdown text and convert to Notion rich text format
        
        Args:
            markdown_text: Markdown text to parse
            
        Returns:
            List of rich text objects for Notion
        """
        import re
        
        rich_text_blocks = []
        
        # Split text into segments while preserving markdown
        # Pattern to match markdown links: [text](url)
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        
        # Find all matches
        matches = list(re.finditer(link_pattern, markdown_text))
        
        if not matches:
            # No markdown links found, return as plain text
            return [{
                "type": "text",
                "text": {
                    "content": markdown_text
                }
            }]
        
        # Process text with markdown links
        last_end = 0
        
        for match in matches:
            # Add text before the link
            if match.start() > last_end:
                plain_text = markdown_text[last_end:match.start()]
                if plain_text:
                    rich_text_blocks.append({
                        "type": "text",
                        "text": {
                            "content": plain_text
                        }
                    })
            
            # Add the link
            link_text = match.group(1)
            link_url = match.group(2)
            
            # Ensure URL has protocol
            if not link_url.startswith(('http://', 'https://')):
                link_url = 'https://' + link_url
            
            rich_text_blocks.append({
                "type": "text",
                "text": {
                    "content": link_text,
                    "link": {
                        "url": link_url
                    }
                }
            })
            
            last_end = match.end()
        
        # Add remaining text after the last link
        if last_end < len(markdown_text):
            plain_text = markdown_text[last_end:]
            if plain_text:
                rich_text_blocks.append({
                    "type": "text",
                    "text": {
                        "content": plain_text
                    }
                })
        
        return rich_text_blocks

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
            # Log the user message content for debugging
            log.debug(f"Notion endpoint: User message content: {issue.user_message[:200]}...")
            
            # Clean the user message to remove any CSS or unwanted content
            cleaned_message = self._clean_user_message(issue.user_message)
            
            # Add heading for Issue Description
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "Issue Description"
                            }
                        }
                    ]
                }
            })
            
            # Add the cleaned user message as a paragraph with markdown parsing
            rich_text_blocks = self._parse_markdown_to_rich_text(cleaned_message)
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": rich_text_blocks
                }
            })
        
        # Add collected data
        if issue.collected_data:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "Collected Data"
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
                                "content": "System information, environment variables, and collected data are available in the attached JSON file."
                            }
                        }
                    ]
                }
            })
        
        # Note: Attachments are handled separately via the Attachments field in the database
        # Note: Timestamp is automatically handled by Notion's Created Time field
        
        return blocks



    def _upload_attachments_to_page(self, issue: DebuglyIssue, page_id: str):
        """
        Upload all attachments and add them to the Attachments field
        
        Args:
            issue: DebuglyIssue object
            page_id: ID of the Notion page to upload files to
        """
        # Check if Attachments field exists in database schema
        if not hasattr(self, '_database_properties') or "Attachments" not in self._database_properties:
            log.debug("Notion endpoint: No Attachments field found, skipping file upload")
            return
        
        all_attachments = self.get_safe_attachments(issue)
        
        if not all_attachments:
            return
        
        log.debug(f"Notion endpoint: Uploading {len(all_attachments)} attachments to page {page_id}")
        
        uploaded_files = []
        for attachment_path in all_attachments:
            try:
                if os.path.exists(attachment_path):
                    # Upload the file and get the ID
                    file_id = self.upload_file(attachment_path, page_id)
                    log.debug(f"Notion endpoint: Successfully uploaded {os.path.basename(attachment_path)}: {file_id}")
                    
                    # Ensure .log files are displayed with .txt extension in Notion
                    base_name = os.path.basename(attachment_path)
                    name_root, name_ext = os.path.splitext(base_name)
                    display_name = f"{name_root}.txt" if name_ext.lower() == ".log" else base_name

                    # Add to the list of uploaded files using file_upload type
                    uploaded_files.append({
                        "type": "file_upload",
                        "file_upload": {
                            "id": file_id
                        },
                        "name": display_name
                    })
                else:
                    log.warning(f"Notion endpoint: Attachment file not found: {attachment_path}")
            except Exception as e:
                log.warning(f"Notion endpoint: Failed to upload {attachment_path}: {e}")
        
        # Update the page with the uploaded files in the Attachments field
        if uploaded_files:
            self._update_page_attachments(page_id, uploaded_files)

    def _update_page_attachments(self, page_id: str, uploaded_files: list):
        """
        Update the page's Attachments field with the uploaded files
        
        Args:
            page_id: ID of the Notion page
            uploaded_files: List of file objects to add to the Attachments field
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }
        
        data = {
            "properties": {
                "Attachments": {
                    "files": uploaded_files
                }
            }
        }
        
        response = requests.patch(
            f"{self.base_url}/pages/{page_id}",
            headers=headers,
            json=data
        )
        
        if response.status_code != 200:
            log.warning(f"Notion endpoint: Failed to update Attachments field: {response.status_code} - {response.text}")
        else:
            log.debug(f"Notion endpoint: Successfully updated Attachments field with {len(uploaded_files)} files")

    def _add_file_block_to_page(self, page_id: str, file_url: str, file_name: str):
        """
        Add a file block to a Notion page
        
        Args:
            page_id: ID of the Notion page
            file_url: URL of the uploaded file
            file_name: Name of the file
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }
        
        # Create a file block
        block_data = {
            "children": [
                {
                    "object": "block",
                    "type": "file",
                    "file": {
                        "type": "external",
                        "external": {
                            "url": file_url
                        }
                    }
                }
            ]
        }
        
        response = requests.patch(
            f"{self.base_url}/blocks/{page_id}/children",
            headers=headers,
            json=block_data
        )
        
        if response.status_code != 200:
            log.warning(f"Notion endpoint: Failed to add file block for {file_name}: {response.status_code} - {response.text}")
        else:
            log.debug(f"Notion endpoint: Successfully added file block for {file_name}")

    def _validate_database_schema(self):
        """
        Validate that the database exists and has the required properties
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/databases/{self.database_id}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                log.warning(f"Notion endpoint: Failed to retrieve database schema - {response.status_code}: {response.text}")
                return
            
            database_info = response.json()
            properties = database_info.get("properties", {})
            
            # Cache the database properties for later use
            self._database_properties = properties
            
            log.debug(f"Notion endpoint: Database properties: {list(properties.keys())}")
            
            # Check for required properties
            required_properties = ["Title"]
            missing_properties = []
            
            for prop in required_properties:
                if prop not in properties:
                    missing_properties.append(prop)
            
            if missing_properties:
                log.warning(f"Notion endpoint: Missing required properties: {missing_properties}")
            
            # Log all available properties for debugging
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get("type", "unknown")
                log.debug(f"Notion endpoint: Property '{prop_name}' is of type '{prop_type}'")
                
        except Exception as e:
            log.warning(f"Notion endpoint: Database validation failed: {e}")
            return

    def upload_file(self, file_path: str, page_id: str) -> str:
        """
        Upload a file to Notion using the Direct Upload method (3-step process)
        
        Args:
            file_path: Path to the file to upload
            page_id: ID of the Notion page to attach the file to
            
        Returns:
            str: ID of the uploaded file
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Get file info
        file_name = os.path.basename(file_path)
        file_extension = os.path.splitext(file_name)[1].lower()
        
        # Rename .log files to .txt for Notion compatibility
        if file_extension == '.log':
            file_name = file_name.replace('.log', '.txt')
            file_extension = '.txt'
        
        # Determine content type based on file extension
        content_type_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.csv': 'text/csv',
            '.json': 'application/json'
        }
        
        content_type = content_type_map.get(file_extension, 'text/plain')
        
        # Step 1: Create a File Upload object
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }
        
        create_data = {
            "filename": file_name,
            "content_type": content_type
        }
        
        response = requests.post(
            f"{self.base_url}/file_uploads",
            headers=headers,
            json=create_data
        )
        
        if response.status_code != 200:
            log.error(f"Notion endpoint: Failed to create file upload - {response.status_code}: {response.text}")
            raise Exception(f"Failed to create file upload: {response.status_code} - {response.text}")
        
        upload_info = response.json()
        file_upload_id = upload_info["id"]
        upload_url = upload_info["upload_url"]
        
        log.debug(f"Notion endpoint: Created file upload {file_upload_id} for {file_name}")
        
        # Step 2: Upload file contents
        with open(file_path, 'rb') as f:
            files = {
                'file': (file_name, f, content_type)
            }
            
            file_response = requests.post(
                upload_url,
                headers={
                    "Authorization": f"Bearer {self.notion_token}",
                    "Notion-Version": self.notion_version
                },
                files=files
            )
            
        if file_response.status_code != 200:
            log.error(f"Notion endpoint: Failed to upload file content - {file_response.status_code}: {file_response.text}")
            raise Exception(f"Failed to upload file content: {file_response.status_code}")
        
        log.debug(f"Notion endpoint: Successfully uploaded file content for {file_name}")
        
        return file_upload_id

    def _get_or_create_user_id(self, search_term: str) -> str:
        """
        Get a user ID for the given search term in Notion
        
        Args:
            search_term: The search term (name, email, or username)
            
        Returns:
            str: The user ID, or None if not found
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }
        
        try:
            log.debug(f"Notion endpoint: Searching for user with term: '{search_term}'")
            
            # First, try to search for existing users
            search_url = f"{self.base_url}/users/search"
            search_data = {
                "query": search_term,
                "filter": {
                    "value": "person",
                    "property": "object"
                }
            }
            
            log.debug(f"Notion endpoint: Searching for user with query: '{search_term}'")
            log.debug(f"Notion endpoint: Search URL: {search_url}")
            log.debug(f"Notion endpoint: Search data: {search_data}")
            
            response = requests.post(
                search_url,
                headers=headers,
                json=search_data,
                timeout=30
            )
            
            if response.status_code == 200:
                users = response.json().get("results", [])
                log.debug(f"Notion endpoint: Found {len(users)} users in search results")
                
                # Log all found users for debugging
                for i, user in enumerate(users):
                    user_name = user.get("name", "Unknown")
                    user_email = user.get("person", {}).get("email", "No email")
                    user_id = user.get("id", "No ID")
                    log.debug(f"Notion endpoint: User {i+1}: Name='{user_name}', Email='{user_email}', ID='{user_id}'")
                
                # Look for exact name match first
                for user in users:
                    user_name = user.get("name", "")
                    if user_name == search_term:
                        user_id = user.get("id")
                        log.debug(f"Notion endpoint: Found exact name match '{search_term}' with ID: {user_id}")
                        
                        # Validate the user ID format
                        if user_id and len(user_id) == 36 and user_id.count('-') == 4:
                            log.debug(f"Notion endpoint: User ID '{user_id}' appears to be a valid UUID")
                        else:
                            log.warning(f"Notion endpoint: User ID '{user_id}' may not be a valid UUID")
                        
                        # Also validate that the user is of type "person"
                        user_type = user.get("type", "")
                        if user_type == "person":
                            log.debug(f"Notion endpoint: User '{search_term}' is a person type user")
                        else:
                            log.warning(f"Notion endpoint: User '{search_term}' is not a person type (type: {user_type})")
                        
                        return user_id
                
                # Look for exact email match
                for user in users:
                    user_email = user.get("person", {}).get("email", "")
                    if user_email == search_term:
                        user_id = user.get("id")
                        log.debug(f"Notion endpoint: Found exact email match '{search_term}' with ID: {user_id}")
                        return user_id
                

                
                log.debug(f"Notion endpoint: No matching user found for '{search_term}'")
            else:
                log.warning(f"Notion endpoint: User search failed with status {response.status_code}: {response.text}")
            
            # If no user found, we cannot create users via API
            # Notion doesn't allow creating users through the API
            log.warning(f"Notion endpoint: User '{search_term}' not found in workspace. Users must be manually added to the workspace.")
            return None
            
        except Exception as e:
            log.warning(f"Notion endpoint: Error searching for user '{search_term}': {e}")
            return None

    def _list_all_users(self):
        """
        List all users in the Notion workspace for debugging purposes
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version
        }
        
        try:
            # Get all users in the workspace
            response = requests.get(
                f"{self.base_url}/users",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                users = response.json().get("results", [])
                log.debug(f"Notion endpoint: Found {len(users)} total users in workspace")
                
                for i, user in enumerate(users):
                    user_name = user.get("name", "Unknown")
                    user_email = user.get("person", {}).get("email", "No email")
                    user_id = user.get("id", "No ID")
                    user_type = user.get("type", "Unknown")
                    log.debug(f"Notion endpoint: User {i+1}: Name='{user_name}', Email='{user_email}', ID='{user_id}', Type='{user_type}'")
                
                return users
            else:
                log.warning(f"Notion endpoint: Failed to list users - {response.status_code}: {response.text}")
                return []
                
        except Exception as e:
            log.warning(f"Notion endpoint: Error listing users: {e}")
            return []

    def get_success_info(self, result):
        """
        Get Notion-specific success information to display to the user
        
        Args:
            result: The result returned by the submit method (dict with url and page_id)
            
        Returns:
            dict: Dictionary containing success information
        """
        if isinstance(result, dict) and "url" in result:
            return {
                "title": "Notion",
                "message": "Issue successfully created in Notion database",
                "url": result["url"],
                "file_path": None,
                "can_open": True
            }
        else:
            # Fallback for old format
            return {
                "title": "Notion",
                "message": "Issue successfully created in Notion database",
                "url": result if isinstance(result, str) else None,
                "file_path": None,
                "can_open": True
            }