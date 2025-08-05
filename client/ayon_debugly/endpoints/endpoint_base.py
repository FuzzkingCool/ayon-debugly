# -*- coding: utf-8 -*-
# Responsible for handling the endpoints for the Debugly addon

import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.logger import log
 

class EndpointBase(ABC):
    @abstractmethod

    def __init__(self):
        self.initialize()
        self._temp_files = []  # Track temporary files for cleanup

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def submit(self, issue: DebuglyIssue):
        pass

    def get_success_info(self, result):
        """
        Get endpoint-specific success information to display to the user
        
        Args:
            result: The result returned by the submit method
            
        Returns:
            dict: Dictionary containing success information with keys:
                - title: Short title for the endpoint
                - message: Success message
                - url: Clickable URL (if applicable)
                - file_path: File path (if applicable)
                - can_open: Whether the result can be opened/viewed
        """
        return {
            "title": self.__class__.__name__.replace("Endpoint", ""),
            "message": f"Successfully submitted to {self.__class__.__name__.replace('Endpoint', '')}",
            "url": None,
            "file_path": None,
            "can_open": False
        }

    def create_redacted_log_files(self, log_files):
        """
        Create redacted versions of log files for safe upload/storage
        
        Args:
            log_files: List of log file paths
            
        Returns:
            List of paths to redacted log files
        """
        redacted_files = []
        
        for log_file in log_files:
            try:
                if not os.path.exists(log_file):
                    continue
                
                # Read the original log file
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Apply redaction
                from ayon_debugly.collectors.collector_base import redact_log_content
                redacted_content = redact_log_content(content)
                
                # Create a temporary redacted file
                base_name = os.path.basename(log_file)
                name, ext = os.path.splitext(base_name)
                redacted_file = tempfile.NamedTemporaryFile(
                    delete=False, 
                    suffix=f"_redacted{ext}", 
                    prefix=f"debugly_{name}_",
                    mode='w',
                    encoding='utf-8'
                )
                
                redacted_file.write(redacted_content)
                redacted_file.close()
                
                redacted_files.append(redacted_file.name)
                self._temp_files.append(redacted_file.name)  # Track for cleanup
                log.debug(f"Endpoint: Created redacted log file: {os.path.basename(log_file)}")
                
            except Exception as e:
                log.warning(f"Endpoint: Failed to create redacted version of {log_file}: {e}")
                # If redaction fails, skip this file for safety
                continue
        
        return redacted_files

    def get_safe_attachments(self, issue: DebuglyIssue):
        """
        Get a list of attachments with redacted log files for safe submission
        
        Args:
            issue: DebuglyIssue object
            
        Returns:
            List of file paths (with redacted log files)
        """
        all_attachments = []
        
        # Add user attachments
        if issue.attachments:
            all_attachments.extend(issue.attachments)
        
        # Add screenshot
        if issue.screenshot:
            all_attachments.append(issue.screenshot)
        
        # Add redacted log files
        if issue.log_files:
            redacted_log_files = self.create_redacted_log_files(issue.log_files)
            all_attachments.extend(redacted_log_files)
        
        # Add collected data file
        if issue.collected_data_file:
            all_attachments.append(issue.collected_data_file)
        
        return all_attachments

    def cleanup_temp_files(self):
        """
        Clean up all temporary files created by this endpoint
        """
        for temp_file in self._temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
                    log.debug(f"Endpoint: Cleaned up temporary file: {os.path.basename(temp_file)}")
            except Exception as e:
                log.warning(f"Endpoint: Failed to cleanup temporary file {temp_file}: {e}")
        
        self._temp_files.clear()

