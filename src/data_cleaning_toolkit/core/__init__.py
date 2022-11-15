"""Core engine, errors and pipeline orchestration (lazy imports)."""

__all__ = [
    "CleanResult",
    "CleaningEngine",
    "ConfigError",
    "DataImportError",
    "LimitExceededError",
    "OutputError",
    "RuleError",
    "SafetyError",
    "ToolkitError",
    "UnsupportedFormatError",
]


def __getattr__(name: str):
    if name in {"CleanResult", "CleaningEngine"}:
        from . import engine

        return getattr(engine, name)
    if name in __all__:
        from . import errors

        return getattr(errors, name)
    raise AttributeError(name)
