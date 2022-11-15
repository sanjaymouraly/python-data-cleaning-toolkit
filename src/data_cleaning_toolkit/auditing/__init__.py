"""Audit trail: change records, run artifact persistence."""

from .audit import AuditCollector  # noqa: F401


def __getattr__(name: str):  # lazy: run_io pulls in reporters/exporters
    if name == "save_run":
        from .run_io import save_run

        return save_run
    raise AttributeError(name)
