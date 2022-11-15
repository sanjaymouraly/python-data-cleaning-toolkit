"""Typed error hierarchy for the data cleaning toolkit.

Every error carries a machine-readable ``code`` so CLIs, the dashboard and
library consumers can react predictably instead of string-matching messages.
"""

from __future__ import annotations


class ToolkitError(Exception):
    """Base class for all toolkit errors."""

    code = "toolkit_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ConfigError(ToolkitError):
    """Raised when a cleaning configuration is missing, malformed or invalid."""

    code = "config_error"


class DataImportError(ToolkitError):
    """Raised when a file cannot be read as a supported dataset."""

    code = "import_error"


class UnsupportedFormatError(DataImportError):
    """Raised for file formats the toolkit deliberately does not process."""

    code = "unsupported_format"


class LimitExceededError(ToolkitError):
    """Raised when a file/dataset exceeds configured safety limits."""

    code = "limit_exceeded"


class RuleError(ToolkitError):
    """Raised when a cleaning rule fails or is misconfigured at runtime."""

    code = "rule_error"


class OutputError(ToolkitError):
    """Raised when writing or validating output files fails."""

    code = "output_error"


class SafetyError(ToolkitError):
    """Raised when an operation would violate a data-safety guarantee."""

    code = "safety_error"
