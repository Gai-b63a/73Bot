"""Compatibility imports for the isolated synthesis worker."""
from .speech.worker import WorkerClient, WorkerFailure

__all__ = ["WorkerClient", "WorkerFailure"]
