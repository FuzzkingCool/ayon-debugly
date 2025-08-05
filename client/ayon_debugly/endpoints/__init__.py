# -*- coding: utf-8 -*-
from .endpoint_base import EndpointBase
from .endpoint_github import EndpointGitHub
from .endpoint_notion import EndpointNotion
from .endpoint_shared_folder import EndpointSharedFolder

__all__ = [
    "EndpointBase",
    "EndpointJira",
    "EndpointGitHub", 
    "EndpointNotion",
    "EndpointSharedFolder"
] 