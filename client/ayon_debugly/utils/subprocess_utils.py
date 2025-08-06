# -*- coding: utf-8 -*-
"""
Cross-platform subprocess utilities that hide command windows.
"""

import os
import sys
import subprocess
from typing import List, Optional, Union, Dict, Any


def get_subprocess_kwargs() -> Dict[str, Any]:
    """
    Get cross-platform subprocess kwargs to hide command windows.
    
    Returns:
        Dict containing kwargs for subprocess calls to hide windows
    """
    kwargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'text': True,
    }
    
    if sys.platform.startswith('win'):
        # Windows: Use CREATE_NO_WINDOW flag to hide console window
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    elif sys.platform == 'darwin':
        # macOS: Use os.devnull for input/output to hide terminal
        kwargs['stdin'] = open(os.devnull, 'r')
        kwargs['stdout'] = open(os.devnull, 'w')
        kwargs['stderr'] = open(os.devnull, 'w')
    else:
        # Linux: Use os.devnull for input/output to hide terminal
        kwargs['stdin'] = open(os.devnull, 'r')
        kwargs['stdout'] = open(os.devnull, 'w')
        kwargs['stderr'] = open(os.devnull, 'w')
    
    return kwargs


def run_silent_subprocess(
    args: Union[str, List[str]], 
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess:
    """
    Run a subprocess silently (no visible command window).
    
    Args:
        args: Command and arguments to run
        timeout: Timeout in seconds
        cwd: Working directory
        env: Environment variables
        
    Returns:
        CompletedProcess object with result
        
    Raises:
        subprocess.TimeoutExpired: If the command times out
        subprocess.CalledProcessError: If the command fails
    """
    kwargs = get_subprocess_kwargs()
    
    if timeout is not None:
        kwargs['timeout'] = timeout
    if cwd is not None:
        kwargs['cwd'] = cwd
    if env is not None:
        kwargs['env'] = env
    
    return subprocess.run(args, **kwargs)


def check_output_silent(
    args: Union[str, List[str]], 
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None
) -> str:
    """
    Run a subprocess silently and return its output.
    
    Args:
        args: Command and arguments to run
        timeout: Timeout in seconds
        cwd: Working directory
        env: Environment variables
        
    Returns:
        Command output as string
        
    Raises:
        subprocess.TimeoutExpired: If the command times out
        subprocess.CalledProcessError: If the command fails
    """
    kwargs = get_subprocess_kwargs()
    
    if timeout is not None:
        kwargs['timeout'] = timeout
    if cwd is not None:
        kwargs['cwd'] = cwd
    if env is not None:
        kwargs['env'] = env
    
    result = subprocess.run(args, **kwargs)
    result.check_returncode()
    return result.stdout


def popen_silent(
    args: Union[str, List[str]], 
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None
) -> subprocess.Popen:
    """
    Create a silent subprocess using Popen.
    
    Args:
        args: Command and arguments to run
        cwd: Working directory
        env: Environment variables
        
    Returns:
        Popen object
    """
    kwargs = get_subprocess_kwargs()
    
    if cwd is not None:
        kwargs['cwd'] = cwd
    if env is not None:
        kwargs['env'] = env
    
    return subprocess.Popen(args, **kwargs) 