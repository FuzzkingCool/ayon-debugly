# -*- coding: utf-8 -*-
"""
Dynamic collector discovery and registration system.
Automatically discovers all collectors in this folder and provides a clean interface.
"""

import os
import importlib
import inspect
from typing import Dict, List, Type, Any
from ayon_debugly.collectors.collector_base import CollectorBase

# Collector registry
_collectors: Dict[str, Type[CollectorBase]] = {}
_collector_names: Dict[str, str] = {}

def _discover_collectors():
    """Discover all collector classes in this package"""
    current_dir = os.path.dirname(__file__)
    
    for filename in os.listdir(current_dir):
        if filename.endswith('.py') and not filename.startswith('_'):
            module_name = filename[:-3]  # Remove .py extension
            
            # Skip base module
            if module_name == 'collector_base':
                continue
                
            try:
                # Import the module
                module = importlib.import_module(f'.{module_name}', package=__name__)
                
                # Find collector classes in the module
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, CollectorBase) and 
                        obj != CollectorBase):
                        
                        # Generate a friendly name from the class name
                        friendly_name = name.replace('Collector', '').replace('_', ' ').title()
                        
                        # Register the collector
                        _collectors[module_name] = obj
                        _collector_names[module_name] = friendly_name
                        
            except Exception as e:
                # Log error but continue with other collectors
                print(f"Warning: Could not load collector {module_name}: {e}")
                import traceback
                traceback.print_exc()

def get_collectors() -> Dict[str, Type[CollectorBase]]:
    """Get all discovered collectors"""
    if not _collectors:
        _discover_collectors()
    return _collectors.copy()

def get_collector_names() -> Dict[str, str]:
    """Get friendly names for all collectors"""
    if not _collector_names:
        _discover_collectors()
    return _collector_names.copy()

def get_collector_pairs() -> List[tuple]:
    """Get (friendly_name, collector_class) pairs for easy iteration"""
    collectors = get_collectors()
    names = get_collector_names()
    
    pairs = []
    for module_name, collector_class in collectors.items():
        friendly_name = names.get(module_name, module_name.replace('_', ' ').title())
        pairs.append((friendly_name, collector_class))
    
    return pairs

def create_collector_instance(module_name: str, **kwargs) -> CollectorBase:
    """Create an instance of a collector by module name"""
    collectors = get_collectors()
    if module_name not in collectors:
        raise ValueError(f"Collector '{module_name}' not found")
    
    return collectors[module_name](**kwargs)

# Auto-discover on import
_discover_collectors()
