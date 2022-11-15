"""Configuration and schema validation helpers.

Validation lives in ``config.schema`` (Pydantic) and in the rule registry;
this package re-exports the user-facing helpers.
"""

from ..config.schema import CleaningConfig, parse_config  # noqa: F401
