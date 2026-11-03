"""Single-process bench service admission, released by the OS if the process exits."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

@contextmanager
def service_owner(directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    guard=directory/'burst-service-lock.sqlite3'
    with_owner=sqlite3.connect(guard,timeout=0,isolation_level=None)
    try:
        with_owner.execute('BEGIN IMMEDIATE')
        yield
    finally:
        with_owner.close()
