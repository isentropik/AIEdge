"""Flush directory entries on Linux after persistent file creation or rename.

Windows local tests retain file fsync and atomic replacement, but do not claim
POSIX directory durability. The filesystem and storage hardware must also honor
flushes; this helper is not evidence of physical power-loss recovery.
"""
import os

DIRECTORY_FSYNC = os.name == 'posix'

def sync_directory(path):
    if not DIRECTORY_FSYNC:return False
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return True
