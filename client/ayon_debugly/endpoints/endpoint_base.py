# Responsible for handling the endpoints for the Debugly addon

import os
import shutil
from abc import ABC, abstractmethod
from ayon_debugly.debugly_issue import DebuglyIssue
 

class EndpointBase(ABC):
    @abstractmethod

    def __init__(self):
        self.initialize()

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def submit(self, issue: DebuglyIssue):
        pass

