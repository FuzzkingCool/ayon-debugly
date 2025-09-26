import base64
import html as _html
import io
import threading
import zipfile
from typing import Any, Optional

import requests

# Use nxtools logging if available, otherwise use standard logging
try:
    from nxtools import logging as log
except ImportError:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    log = logging.getLogger(__name__)


class NotionService:
    def __init__(self, token: str, database_id: str):
        if not token:
            raise ValueError("Notion API token is required")
        if not database_id:
            raise ValueError("Database ID is required")

        self.token = token
        self.database_id = database_id
        self.notion_version = "2025-09-03"  # Latest version with data sources
        self.base_url = "https://api.notion.com/v1"
        self._data_source_id = None

        log.info(
            f"NotionService initialized with database_id: {database_id[:8]}..., version: {self.notion_version}"
        )
        log.debug(f"Token length: {len(token) if token else 0}")
        log.debug(f"Base URL: {self.base_url}")

        # Validate database ID format (UUID with or without dashes)
        clean_db_id = database_id.replace("-", "")
        if len(clean_db_id) != 32 or not all(
            c in "0123456789abcdefABCDEF" for c in clean_db_id
        ):
            log.warning(f"Database ID format may be invalid: {database_id}")
            log.warning("Expected format: 32 hex characters (with or without dashes)")

        log.info("Using 2025-09-03 API - data source operations")

    def test_connection(self) -> dict[str, Any]:
        """Test the Notion API connection and database access."""
        log.info("Testing Notion API connection...")

        # First test basic network connectivity
        try:
            log.info("Testing basic network connectivity to api.notion.com...")
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(600)  # 10 minutes
            result = sock.connect_ex(("api.notion.com", 443))
            sock.close()

            if result != 0:
                return {
                    "success": False,
                    "error": f"Cannot connect to api.notion.com:443 (network error: {result}). Check firewall/proxy settings.",
                }
            log.info("✓ Basic network connectivity to api.notion.com:443 successful")
        except Exception as e:
            return {
                "success": False,
                "error": f"Network connectivity test failed: {str(e)}",
            }

        try:
            # Test basic API access
            url = f"{self.base_url}/users/me"
            headers = self._headers()

            log.info("Testing Notion API authentication...")
            log.debug("Testing user endpoint with timeout=30 seconds...")
            resp = requests.get(
                url, headers=headers, timeout=(30, 600)  # 30s connect, 10min read
            )  # 5s connect, 30s read
            log.debug(f"User endpoint response: {resp.status_code}")

            if resp.status_code == 401:
                return {
                    "success": False,
                    "error": "Authentication failed - invalid API token",
                }
            elif resp.status_code != 200:
                log.error(f"API response text: {resp.text}")
                return {
                    "success": False,
                    "error": f"API access failed: {resp.status_code} - {resp.text}",
                }

            user_data = resp.json()
            log.info(f"✓ Connected as: {user_data.get('name', 'Unknown user')}")

            # Test database access with data source discovery
            try:
                log.info("Testing database access...")
                data_source_id = self._get_data_source_id()
                if data_source_id:
                    log.info(f"✓ Successfully discovered data source ID: {data_source_id[:8]}...")
                    # Test database properties access
                    properties = self._get_database_properties()
                    log.info(f"✓ Database accessible with {len(properties)} properties")
                    return {
                        "success": True,
                        "user": user_data.get("name", "Unknown"),
                        "data_source_id": data_source_id[:8] + "...",
                        "database_properties": len(properties),
                        "api_version": "2025-09-03 (data source)",
                    }
                else:
                    log.warning("No data source found, testing database fallback...")
                    # Test database properties access
                    properties = self._get_database_properties()
                    log.info(f"✓ Database accessible with {len(properties)} properties")
                    return {
                        "success": True,
                        "user": user_data.get("name", "Unknown"),
                        "database_properties": len(properties),
                        "api_version": "2025-09-03 (database fallback)",
                    }
            except Exception as e:
                log.error(f"Database access failed: {e}")
                return {"success": False, "error": f"Database access failed: {str(e)}"}

        except requests.exceptions.Timeout as e:
            log.error(f"Request timeout: {e}")
            return {
                "success": False,
                "error": "Request timeout - try increasing timeout values or check network connectivity",
            }
        except requests.exceptions.ConnectionError as e:
            log.error(f"Connection error: {e}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. Check proxy settings or firewall.",
            }
        except Exception as e:
            log.error(f"Connection test failed: {e}")
            return {"success": False, "error": f"Connection failed: {str(e)}"}

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }
        log.debug(f"Generated headers with Notion-Version: {self.notion_version}")
        return headers

    def _get_data_source_id(self) -> Optional[str]:
        """
        Get the data source ID for the database.
        This is required for the 2025-09-03 API version.
        Follows the official upgrade guide: https://developers.notion.com/docs/upgrade-guide-2025-09-03
        """
        if self._data_source_id is not None:
            log.debug(f"Using cached data_source_id: {self._data_source_id[:8]}...")
            return self._data_source_id

        log.info(f"Discovering data source ID for database: {self.database_id[:8]}...")
        url = f"{self.base_url}/databases/{self.database_id}"
        headers = self._headers()

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            log.debug(f"Database API response status: {resp.status_code}")

            if resp.status_code == 404:
                log.error(f"Database not found: {self.database_id}")
                return None

            if resp.status_code == 401:
                log.error("Authentication failed - check Notion API token")
                return None

            if resp.status_code != 200:
                log.error(f"Failed to get database info. Status: {resp.status_code}")
                log.error(f"Response text: {resp.text}")
                return None

            data = resp.json()
            log.debug(f"Database response keys: {list(data.keys())}")
            log.debug(f"Full database response: {data}")
            
            # Check for data_sources field (2025-09-03 API)
            if "data_sources" in data:
                data_sources = data.get("data_sources", [])
                log.info(f"Found {len(data_sources)} data sources in database")
                log.debug(f"Data sources: {data_sources}")

                if not data_sources:
                    log.error("No data sources found in database response")
                    log.debug(f"Database response: {data}")
                    return None

                # Use the first data source (canonical approach per upgrade guide)
                selected_source = data_sources[0]
                self._data_source_id = selected_source["id"]
                source_name = selected_source.get("name", "Unknown")

                log.info(f"✓ Selected data source: '{source_name}' (ID: {self._data_source_id[:8]}...)")
                return self._data_source_id
            else:
                log.warning("No 'data_sources' field found in database response")
                log.warning("This database may not support 2025-09-03 API - falling back to database_id")
                log.debug(f"Database response: {data}")
                # For databases without data sources, we'll use database_id directly
                return None

        except Exception as e:
            log.error(f"Error fetching data source ID: {e}")
            log.debug(f"Exception details: {type(e).__name__}: {str(e)}")
            return None

    def _get_database_properties(self) -> dict[str, Any]:
        """
        Get database properties using the appropriate endpoint for 2025-09-03 API.
        """
        log.debug(f"Fetching database properties for: {self.database_id[:8]}...")

        try:
            # 2025-09-03 API: Try data source endpoint first
            data_source_id = self._get_data_source_id()
            if data_source_id:
                url = f"{self.base_url}/data_sources/{data_source_id}"
                log.debug(f"Getting properties from data source: {data_source_id[:8]}...")
                resp = requests.get(url, headers=self._headers(), timeout=(30, 600))
                resp.raise_for_status()
                data = resp.json()
                properties = data.get("properties", {})
                log.debug(f"Got {len(properties)} properties from data source")
                return properties
            else:
                # Fallback to database endpoint
                url = f"{self.base_url}/databases/{self.database_id}"
                log.debug(f"Getting properties from database: {self.database_id[:8]}...")
                resp = requests.get(url, headers=self._headers(), timeout=(30, 600))
                resp.raise_for_status()
                data = resp.json()
                properties = data.get("properties", {})
                log.debug(f"Got {len(properties)} properties from database")
                return properties
        except Exception as e:
            log.error(f"Failed to get properties: {e}")
            raise Exception(f"Could not access database properties: {e}")

    def submit_issue(
        self,
        title: str,
        user_message: str,
        collected_data: dict[str, Any],
        tags: list[str],
        attachments_zip_b64: Optional[str],
        assignee_id: str,
        idempotency_key: Optional[str] = None,
        async_attachments: bool = True,
        rich_text: Optional[list[dict[str, Any]]] = None,
        heading: str = "",
        blocks: Optional[list[dict[str, Any]]] = None,
        title_property: Optional[str] = None,
    ) -> dict[str, str]:
        log.info(f"Starting submit_issue with title: '{title[:50]}...'")
        log.debug(f"User message length: {len(user_message) if user_message else 0}")
        log.debug(
            f"Collected data keys: {list(collected_data.keys()) if collected_data else []}"
        )
        log.debug(f"Tags: {tags}")
        log.debug(f"Assignee ID: {assignee_id}")
        log.debug(f"Has attachments: {bool(attachments_zip_b64)}")
        log.debug(f"Has blocks: {bool(blocks)}")
        log.debug(f"Title property: {title_property}")

        log.debug("Building page properties...")
        properties = self._build_properties(
            title, tags, collected_data, assignee_id, title_property
        )
        log.debug(f"Built properties: {list(properties.keys())}")

        # Prefer prebuilt blocks from client
        if blocks and isinstance(blocks, list) and len(blocks) > 0:
            log.debug(f"Using {len(blocks)} client-provided blocks")
            children = blocks
        else:
            log.debug("Building children from user message")
            children = self._build_children(
                user_message, rich_text=rich_text, heading=heading
            )
            log.debug(f"Built {len(children)} children blocks")

        # 2025-09-03 API: Try data_source_id first, fallback to database_id
        # Note: children are added separately after page creation
        data_source_id = self._get_data_source_id()
        
        if data_source_id:
            # Use data_source_id (2025-09-03 API approach)
            payload = {
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": data_source_id
                },
                "properties": properties,
                "icon": {"type": "emoji", "emoji": "❓"},
            }
            log.info(f"Using data_source_id for page creation: {data_source_id[:8]}...")
        else:
            # Fallback to database_id (still supported in 2025-09-03)
            payload = {
                "parent": {
                    "type": "database_id",
                    "database_id": self.database_id
                },
                "properties": properties,
                "icon": {"type": "emoji", "emoji": "❓"},
            }
            log.info(f"Using database_id for page creation: {self.database_id[:8]}...")
        log.debug(f"Page creation payload: {payload}")
        log.debug(f"Page creation payload parent: {payload['parent']}")
        log.debug(f"Page creation payload properties: {payload['properties']}")
        log.debug(f"Page creation payload icon: {payload['icon']}")

        log.debug(f"Page creation payload parent: {payload['parent']}")
        log.debug(
            f"Page creation payload properties count: {len(payload['properties'])}"
        )
        log.debug(f"Children will be added after page creation: {len(children)} blocks")
        
        # Debug the exact request being made
        log.info(f"Making Notion API request to: {self.base_url}/pages")
        log.info(f"Request headers: {self._headers()}")
        log.info(f"Request payload type: {type(payload)}")
        log.info(f"Request payload size: {len(str(payload))} characters")

        headers = self._headers().copy()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
            log.debug(f"Added idempotency key: {idempotency_key[:8]}...")

        # 2025-09-03 API: Use standard pages endpoint with database_id parent
        url = f"{self.base_url}/pages"
        log.debug(f"Making POST request to pages endpoint: {url}")
        log.debug(f"Request headers: {headers}")
        log.debug(f"Request payload size: {len(str(payload))} characters")

        # More tolerant timeouts and a single retry on transient network errors
        resp = None
        for attempt in range(2):
            try:
                log.debug(f"Page creation attempt {attempt + 1}/2")
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=(30, 600),  # 30s connect, 10min read for large payloads
                )
                log.debug(f"Page creation response status: {resp.status_code}")
                log.debug(f"Page creation response headers: {dict(resp.headers)}")

                if resp.status_code >= 400:
                    log.error(f"Page creation failed with status {resp.status_code}")
                    log.error(f"Response text: {resp.text}")
                    log.error(f"Request URL: {url}")
                    log.error(f"Request headers: {headers}")
                    log.error(f"Request payload: {payload}")
                    
                    # Try to parse error response for more details
                    try:
                        error_data = resp.json()
                        log.error(f"Error response JSON: {error_data}")
                    except:
                        log.error(f"Error response is not JSON: {resp.text}")
                    
                    # Provide specific error messages for common API issues
                    if resp.status_code == 400:
                        error_text = resp.text.lower()
                        log.error(f"400 Error details: {error_text}")
                        
                        if "data_source_id" in error_text:
                            log.error("Data source ID error - trying database_id fallback")
                            # Try fallback to database_id if data_source_id failed
                            if payload["parent"]["type"] == "data_source_id":
                                log.info("Retrying with database_id instead of data_source_id")
                                payload["parent"] = {
                                    "type": "database_id",
                                    "database_id": self.database_id
                                }
                                continue
                        elif "parent" in error_text:
                            log.error("Parent type error - check database permissions")
                        elif "properties" in error_text:
                            log.error("Properties error - check database schema")
                        elif "invalid" in error_text:
                            log.error("Invalid request format - check API version compatibility")
                    
                    # Instead of just raising, preserve the detailed error information
                    try:
                        error_data = resp.json()
                        detailed_error = f"Status {resp.status_code}: {error_data}"
                    except:
                        detailed_error = f"Status {resp.status_code}: {resp.text}"
                    
                    # Raise with detailed error information
                    raise Exception(f"Notion API request failed: {detailed_error}")

                log.debug("Page creation successful")
                break
            except requests.exceptions.RequestException as e:
                log.error(f"Request exception on attempt {attempt + 1}: {e}")
                if attempt == 1:
                    raise
                # brief backoff
                import time

                log.debug("Retrying after 1 second...")
                time.sleep(1.0)
            except Exception as e:
                log.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt == 1:
                    raise
                import time

                time.sleep(1.0)

        try:
            data = resp.json()
            log.debug(f"Page creation response data keys: {list(data.keys())}")
        except Exception as e:
            log.error(f"Failed to parse JSON response: {e}")
            log.error(f"Raw response text: {resp.text}")
            raise

        page_id = data.get("id", "")
        url = data.get("url", "")
        log.info(f"Successfully created page with ID: {page_id[:8]}...")
        log.info(f"Page URL: {url}")

        # Add children blocks after page creation
        if children and len(children) > 0:
            log.info(f"Adding {len(children)} children blocks to page...")
            try:
                self._add_children_to_page(page_id, children)
                log.info("Successfully added children blocks to page")
            except Exception as e:
                log.warning(f"Failed to add children blocks: {e}")
                # Don't fail the whole submission for this

        # Handle "Add Name to Vote" field after page creation
        self._update_vote_field(page_id, collected_data)

        # Always upload attachments separately after page creation to avoid timeouts
        if attachments_zip_b64 and page_id:
            log.info("Starting asynchronous attachment upload process...")
            if async_attachments:
                # Start attachment upload in background thread
                t = threading.Thread(
                    target=self._safe_attach_wrapper,
                    args=(attachments_zip_b64, page_id),
                    daemon=True,
                )
                t.start()
                log.info("Background attachment upload started")
            else:
                # Upload attachments synchronously (for testing/debugging)
                log.info("Starting synchronous attachment upload...")
                try:
                    self._attach_zip_to_page(attachments_zip_b64, page_id)
                    log.info("Synchronous attachment upload completed")
                except Exception as e:
                    log.warning(f"Synchronous attachment upload failed: {e}")

        return {"url": url, "page_id": page_id}

    def _add_children_to_page(self, page_id: str, children: list[dict[str, Any]]):
        """Add children blocks to a Notion page after creation."""
        if not children:
            return
        
        log.debug(f"Adding {len(children)} children to page {page_id[:8]}...")
        
        # Notion API requires children to be added via the blocks endpoint
        url = f"{self.base_url}/blocks/{page_id}/children"
        headers = self._headers()
        
        payload = {
            "children": children
        }
        
        try:
            resp = requests.patch(url, headers=headers, json=payload, timeout=(30, 600))
            resp.raise_for_status()
            log.debug(f"Successfully added {len(children)} children blocks")
        except Exception as e:
            log.error(f"Failed to add children blocks: {e}")
            raise

    def _build_properties(
        self,
        title: str,
        tags: list[str],
        collected_data: dict[str, Any],
        assignee_id: str,
        title_property_override: Optional[str] = None,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        # Always fetch schema to validate title property key
        db_props = self._get_database_properties()

        # Title
        # Decide title property: prefer override if it exists and is a title; else find first 'title' type; else fallback "Title"
        title_key = None
        if title_property_override and title_property_override in db_props:
            if db_props[title_property_override].get("type") == "title":
                title_key = title_property_override
        if not title_key:
            title_key = next(
                (k for k, v in db_props.items() if v.get("type") == "title"), None
            )
        if not title_key:
            title_key = "Title"
        properties[title_key] = {
            "title": [
                {
                    "type": "text",
                    "text": {"content": title[:2000]},
                }
            ]
        }

        # Tags
        if "Tags" in db_props and tags:
            properties["Tags"] = {"multi_select": [{"name": t} for t in tags if t]}

        # Submitted By - set to current user from collected data
        if "Submitted By" in db_props:
            user_id = self._get_current_user_id(collected_data)
            if user_id:
                properties["Submitted By"] = {"people": [{"id": user_id}]}
        
        # Add Name to Vote - will be handled after page creation
        # (We can't get existing values before the page exists)

        return properties

    def _get_current_user_id(self, collected_data: dict[str, Any]) -> Optional[str]:
        """Get current user ID by finding the real user by email from AYON data."""
        try:
            # Extract user email from AYON collected data
            user_email = None
            if collected_data and "User" in collected_data:
                user_data = collected_data["User"]
                if isinstance(user_data, dict) and "user" in user_data:
                    user_data = user_data["user"]
                user_email = user_data.get("ayon_email")
            
            if not user_email:
                log.warning("No user email found in collected data - cannot find real user")
                return None
            
            log.info(f"Looking for Notion user with email: {user_email}")
            
            # List all users in the workspace to find the real user by email
            headers = self._headers()
            response = requests.get(f"{self.base_url}/users", headers=headers, timeout=600)
            
            if response.status_code == 200:
                users_data = response.json()
                users = users_data.get("results", [])
                
                log.debug(f"Found {len(users)} users in Notion workspace")
                
                # Find user by email
                for user in users:
                    user_id = user.get("id")
                    user_name = user.get("name", "Unknown")
                    user_type = user.get("type", "unknown")
                    
                    # Check person email
                    if user_type == "person":
                        person_data = user.get("person", {})
                        person_email = person_data.get("email", "")
                        
                        if person_email.lower() == user_email.lower():
                            log.info(f"Found matching user: {user_name} (ID: {user_id[:8]}..., email: {person_email})")
                            return user_id
                    
                    log.debug(f"User: {user_name} (ID: {user_id[:8]}..., type: {user_type}, email: {person_email if user_type == 'person' else 'N/A'})")
                
                log.warning(f"No Notion user found with email: {user_email}")
                return None
            else:
                log.warning(f"Failed to list users from Notion API: {response.status_code}")
                return None
        except Exception as e:
            log.warning(f"Failed to get current user ID from Notion API: {e}")
            return None


    def _get_existing_multi_select_values(self, page_id: str, property_name: str) -> list[str]:
        """Get existing values from a multi-select property."""
        try:
            headers = self._headers()
            response = requests.get(
                f"{self.base_url}/pages/{page_id}/properties/{property_name}",
                headers=headers,
                timeout=600  # 10 minutes
            )
            if response.status_code == 200:
                data = response.json()
                return [item.get("id") for item in data.get("multi_select", [])]
            return []
        except Exception as e:
            log.warning(f"Failed to get existing values for {property_name}: {e}")
            return []

    def _update_vote_field(self, page_id: str, collected_data: dict[str, Any]):
        """Update the 'Add Name to Vote' field after page creation."""
        try:
            # Check if the field exists in the database
            db_props = self._get_database_properties()
            if "Add Name to Vote" not in db_props:
                log.debug("No 'Add Name to Vote' field found in database")
                return
            
            user_id = self._get_current_user_id(collected_data)
            if not user_id:
                log.warning("Could not determine current user for vote field")
                return
            
            log.debug(f"Adding user {user_id[:8]}... to vote field")
            
            # For a new page, just add the current user (no existing values to preserve)
            payload = {
                "properties": {
                    "Add Name to Vote": {
                        "multi_select": [{"id": user_id}]
                    }
                }
            }
            
            headers = self._headers()
            response = requests.patch(
                f"{self.base_url}/pages/{page_id}",
                headers=headers,
                json=payload,
                timeout=(30, 600)  # 30s connect, 10min read
            )
        
            if response.status_code == 200:
                log.info(f"Successfully updated 'Add Name to Vote' field for page {page_id[:8]}...")
            else:
                log.warning(f"Failed to update 'Add Name to Vote' field: {response.status_code} - {response.text}")
                
        except Exception as e:
            log.warning(f"Failed to update vote field: {e}")

    def _build_children(
        self,
        user_message: str,
        rich_text: Optional[list[dict[str, Any]]] = None,
        heading: str = "",
    ) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        if user_message or rich_text:
            text_input = user_message or ""
            if "<" in text_input and ">" in text_input:
                text_input = self._html_to_markdown(text_input)
            cleaned = self._clean_user_message(text_input)
            blocks = self._markdown_to_blocks(cleaned)
            if not blocks:
                rt = self._parse_markdown_to_rich_text(cleaned)
                blocks = [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": rt},
                    }
                ]
            children.extend(blocks)
        return children

    def _clean_user_message(self, message: str) -> str:
        """Normalize editor output before markdown parsing.

        - Strip <style>...</style> blocks
        - Remove CSS rules and stray selector lines (e.g. "p,", "li.unchecked::")
        - Collapse extra blank lines
        - Unescape HTML entities (&amp; → &)
        """
        if not message:
            return message

        import re

        text = message

        # Remove any <style> blocks entirely
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)

        # Remove inline CSS one-liners like  p, li { ... }
        text = re.sub(r"(?m)^\s*[^<{\n]{1,60}\{[^}]*\}\s*$", "", text)

        # Remove common leftover selector-only lines the editor sometimes leaves
        text = re.sub(r"(?m)^\s*(p,?\s*$)", "", text)
        text = re.sub(r"(?m)^\s*(hr\s*$)", "", text)
        text = re.sub(r"(?m)^\s*li\.(?:unchecked|checked)::?[^\s]*\s*$", "", text)

        # Collapse 3+ newlines to at most 2
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

        # Unescape HTML entities (e.g., &amp; → &)
        text = _html.unescape(text)

        return text.strip()

    def _html_to_markdown(self, html_text: str) -> str:
        """Best-effort convert small subset of HTML (as produced by our editor)
        into markdown that our block parser understands.

        Handles: h1/h2/h3, hr, b/strong, i/em, br, p, a href.
        """
        import re

        text = html_text

        # Normalize line breaks first
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

        # Headings
        text = re.sub(r"<h1[^>]*>([\s\S]*?)</h1>", r"# \1\n", text, flags=re.IGNORECASE)
        text = re.sub(
            r"<h2[^>]*>([\s\S]*?)</h2>", r"## \1\n", text, flags=re.IGNORECASE
        )
        text = re.sub(
            r"<h3[^>]*>([\s\S]*?)</h3>", r"### \1\n", text, flags=re.IGNORECASE
        )

        # Horizontal rule
        text = re.sub(r"<hr[^>]*>", "\n---\n", text, flags=re.IGNORECASE)

        # Bold/italic
        text = re.sub(
            r"<(?:b|strong)>([\s\S]*?)</(?:b|strong)>",
            r"**\1**",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"<(?:i|em)>([\s\S]*?)</(?:i|em)>", r"*\1*", text, flags=re.IGNORECASE
        )

        # Links
        def _a_to_md(m: re.Match) -> str:
            label = m.group(2) or m.group(1) or ""
            href = m.group(1) or ""
            return f"[{label}]({href})"

        text = re.sub(
            r"<a[^>]*href=\"([^\"]+)\"[^>]*>([\s\S]*?)</a>",
            _a_to_md,
            text,
            flags=re.IGNORECASE,
        )

        # Paragraphs → ensure newline boundaries
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)

        # Strip any remaining tags (defensive)
        text = re.sub(r"<[^>]+>", "", text)

        return text.strip()

    def _parse_markdown_to_rich_text(self, markdown_text: str) -> list[dict[str, Any]]:
        import re

        rich_text_blocks: list[dict[str, Any]] = []
        link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
        matches = list(re.finditer(link_pattern, markdown_text))
        if not matches:
            return [{"type": "text", "text": {"content": markdown_text}}]
        last_end = 0
        for match in matches:
            if match.start() > last_end:
                plain_text = markdown_text[last_end : match.start()]
                if plain_text:
                    rich_text_blocks.append(
                        {"type": "text", "text": {"content": plain_text}}
                    )
            link_text = match.group(1)
            link_url = match.group(2)
            if not link_url.startswith(("http://", "https://")):
                link_url = "https://" + link_url
            rich_text_blocks.append(
                {
                    "type": "text",
                    "text": {"content": link_text, "link": {"url": link_url}},
                }
            )
            last_end = match.end()
        if last_end < len(markdown_text):
            plain_text = markdown_text[last_end:]
            if plain_text:
                rich_text_blocks.append(
                    {"type": "text", "text": {"content": plain_text}}
                )
        return rich_text_blocks

    def _markdown_to_blocks(self, text: str) -> list[dict[str, Any]]:
        import re

        blocks: list[dict[str, Any]] = []

        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if not line:
                i += 1
                continue

            # Headings
            if line.startswith("### "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[4:]}}
                            ]
                        },
                    }
                )
                i += 1
                continue
            if line.startswith("## "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[3:]}}
                            ]
                        },
                    }
                )
                i += 1
                continue
            if line.startswith("# "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_1",
                        "heading_1": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[2:]}}
                            ]
                        },
                    }
                )
                i += 1
                continue

            # Divider
            if re.fullmatch(r"\s*---\s*", line):
                blocks.append({"object": "block", "type": "divider", "divider": {}})
                i += 1
                continue

            # Quote
            if line.lstrip().startswith("> "):
                quote_text = line.lstrip()[2:]
                blocks.append(
                    {
                        "object": "block",
                        "type": "quote",
                        "quote": {
                            "rich_text": self._parse_markdown_to_rich_text(quote_text)
                        },
                    }
                )
                i += 1
                continue

            # Bulleted list
            if line.lstrip().startswith("- "):
                while i < len(lines) and lines[i].lstrip().startswith("- "):
                    item_text = lines[i].lstrip()[2:]
                    blocks.append(
                        {
                            "object": "block",
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": self._parse_markdown_to_rich_text(
                                    item_text
                                )
                            },
                        }
                    )
                    i += 1
                continue

            # Numbered list
            if re.match(r"\s*\d+\.\s+", line):
                while i < len(lines) and re.match(r"\s*\d+\.\s+", lines[i]):
                    item_text = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                    blocks.append(
                        {
                            "object": "block",
                            "type": "numbered_list_item",
                            "numbered_list_item": {
                                "rich_text": self._parse_markdown_to_rich_text(
                                    item_text
                                )
                            },
                        }
                    )
                    i += 1
                continue

            # Paragraph - collect until blank line
            para_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                para_lines.append(lines[i])
                i += 1
            para_text = "\n".join(para_lines)
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": self._parse_markdown_to_rich_text(para_text)
                    },
                }
            )

        return blocks

    def _attach_zip_to_page(self, attachments_zip_b64: str, page_id: str):
        """
        Extract and upload files from ZIP to Notion page.
        Process files one by one to avoid memory issues with large attachments.
        """
        log.info(f"Starting attachment upload for page {page_id[:8]}...")
        
        try:
            raw = base64.b64decode(attachments_zip_b64)
            log.debug(f"Decoded ZIP size: {len(raw)} bytes")
        except Exception as e:
            log.error(f"Failed to decode ZIP data: {e}")
            return

        try:
            with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
                uploaded_files: list[dict[str, Any]] = []
                file_list = zf.infolist()
                
                # Filter files to only include meaningful attachments
                relevant_files = [
                    zi for zi in file_list
                    if not zi.is_dir() and (
                        zi.filename.startswith("attachments/")
                        or zi.filename.startswith("screenshot/")
                        or zi.filename.startswith("logs/")
                    )
                ]
                
                log.info(f"Found {len(relevant_files)} files to upload (out of {len(file_list)} total)")

                def guess_content_type(name: str) -> str:
                    name_l = name.lower()
                    content_types = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg", 
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".pdf": "application/pdf",
                        ".txt": "text/plain",
                        ".log": "text/plain",
                        ".md": "text/markdown",
                        ".csv": "text/csv",
                        ".json": "application/json",
                    }
                    for ext, ct in content_types.items():
                        if name_l.endswith(ext):
                            return ct
                    return "text/plain"

                # Process files one by one
                for i, zi in enumerate(relevant_files):
                    try:
                        log.debug(f"Processing file {i+1}/{len(relevant_files)}: {zi.filename}")
                        
                        # Check file size (Notion has limits)
                        if zi.file_size > 100 * 1024 * 1024:  # 100MB limit
                            log.warning(f"Skipping large file {zi.filename} ({zi.file_size} bytes)")
                            continue

                        file_bytes = zf.read(zi)
                        base_name = zi.filename.split("/")[-1]

                        # Rename .log to .txt for Notion compatibility
                        if base_name.lower().endswith(".log"):
                            display_name = base_name[:-4] + ".txt"
                        else:
                            display_name = base_name

                        content_type = guess_content_type(display_name)
                        
                        log.debug(f"Uploading {display_name} ({len(file_bytes)} bytes, {content_type})")
                        file_id = self._upload_file_bytes(display_name, content_type, file_bytes)
                        
                        uploaded_files.append({
                            "type": "file_upload",
                            "file_upload": {"id": file_id},
                            "name": display_name,
                        })
                        
                        log.debug(f"Successfully uploaded {display_name} with ID: {file_id[:8]}...")
                        
                    except Exception as e:
                        log.warning(f"Failed to upload {zi.filename}: {e}")
                        continue

                # Update page with all uploaded files at once
                if uploaded_files:
                    log.info(f"Updating page with {len(uploaded_files)} uploaded files...")
                    self._update_page_attachments(page_id, uploaded_files)
                    log.info("Successfully updated page with attachments")
                else:
                    log.warning("No files were successfully uploaded")

        except zipfile.BadZipFile as e:
            log.error(f"Invalid ZIP file: {e}")
        except Exception as e:
            log.error(f"Error processing ZIP file: {e}")
            import traceback
            log.error(f"Traceback: {traceback.format_exc()}")

    def _upload_file_bytes(
        self, file_name: str, content_type: str, file_bytes: bytes
    ) -> str:
        """
        Upload file bytes to Notion using the 3-step upload process.
        Handles large files with appropriate timeouts.
        """
        file_size = len(file_bytes)
        log.debug(f"Starting upload for {file_name} ({file_size} bytes)")
        
        # Step 1: Create file upload object
        create_payload = {"filename": file_name, "content_type": content_type}
        
        try:
            resp = requests.post(
                f"{self.base_url}/file_uploads",
                headers=self._headers(),
                json=create_payload,
                timeout=(30, 600),  # 30s connect, 10min read
            )
            resp.raise_for_status()
            
            info = resp.json()
            file_upload_id = info["id"]
            upload_url = info["upload_url"]
            
            log.debug(f"Created upload object {file_upload_id[:8]}... for {file_name}")
            
        except Exception as e:
            log.error(f"Failed to create upload object for {file_name}: {e}")
            raise

        # Step 2: Upload file content to the provided URL
        try:
            # Use very generous timeout for file uploads (10 minutes)
            upload_timeout = 600  # 10 minutes for all file uploads
            log.debug(f"Using upload timeout: {upload_timeout}s for {file_size} bytes")
            
            files = {"file": (file_name, file_bytes, content_type)}
            resp2 = requests.post(
                upload_url,
                headers={
                    "Authorization": self._headers()["Authorization"],
                    "Notion-Version": self.notion_version,
                },
                files=files,
                timeout=(30, upload_timeout),  # 30s connect, 10min read timeout
            )
            resp2.raise_for_status()
            
            log.debug(f"Successfully uploaded content for {file_name}")
            return file_upload_id
            
        except requests.exceptions.Timeout as e:
            log.error(f"Upload timeout for {file_name} after {upload_timeout}s: {e}")
            raise Exception(f"File upload timeout for {file_name}")
        except Exception as e:
            log.error(f"Failed to upload content for {file_name}: {e}")
            raise

    def _add_file_block_to_page(self, page_id: str, file_id: str, filename: str):
        """Add a file block to a Notion page."""
        try:
            headers = self._headers()
            
            # Create a file block
            block_data = {
                "children": [
                    {
                        "object": "block",
                        "type": "file",
                        "file": {
                            "type": "file_upload",
                            "file_upload": {"id": file_id}
                        }
                    }
                ]
            }
            
            response = requests.patch(
                f"{self.base_url}/blocks/{page_id}/children",
                headers=headers,
                json=block_data,
                timeout=(30, 600)  # 30s connect, 10min read
            )
            
            if response.status_code != 200:
                log.warning(f"Failed to add file block for {filename}: {response.status_code} - {response.text}")
            else:
                log.debug(f"Successfully added file block for {filename}")
                
        except Exception as e:
            log.error(f"Failed to add file block for {filename}: {e}")

    def _update_page_attachments(
        self, page_id: str, uploaded_files: list[dict[str, Any]]
    ):
        """Update page with attachment files. This works the same for both API versions."""
        log.info(
            f"Updating page {page_id[:8]}... with {len(uploaded_files)} attachments"
        )
        
        # Split into smaller batches if we have many files to avoid request size limits
        batch_size = 10  # Notion can handle ~10 files per request reliably
        
        for i in range(0, len(uploaded_files), batch_size):
            batch = uploaded_files[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(uploaded_files) + batch_size - 1) // batch_size
            
            log.debug(f"Updating page with batch {batch_num}/{total_batches} ({len(batch)} files)")
            
            payload = {"properties": {"Attachments": {"files": batch}}}

            try:
                resp = requests.patch(
                    f"{self.base_url}/pages/{page_id}",
                    headers=self._headers(),
                    json=payload,
                    timeout=(30, 600),  # 30s connect, 10min read
                )
                resp.raise_for_status()
                log.debug(f"Successfully updated page with batch {batch_num}")
                
                # Small delay between batches to avoid rate limiting
                if batch_num < total_batches:
                    import time
                    time.sleep(1)
                    
            except Exception as e:
                log.warning(f"Failed to update page with batch {batch_num}: {e}")
                # Continue with other batches - partial success is better than total failure
                continue

        log.info(f"Completed page attachment update process")

    def _safe_attach_wrapper(self, attachments_zip_b64: str, page_id: str) -> None:
        """
        Safe wrapper for attachment upload that doesn't fail the main process.
        Runs in background thread.
        """
        try:
            log.info(f"Background attachment upload starting for page {page_id[:8]}...")
            self._attach_zip_to_page(attachments_zip_b64, page_id)
            log.info(f"Background attachment upload completed for page {page_id[:8]}...")
        except Exception as e:
            # Background failures are non-fatal but should be logged
            log.error(f"Background attachment upload failed for page {page_id[:8]}...: {e}")
            import traceback
            log.error(f"Background upload traceback: {traceback.format_exc()}")
            # Don't raise - this runs in background thread
