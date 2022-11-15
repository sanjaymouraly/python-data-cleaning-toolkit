"""Cleaning rule implementations and the rule registry.

Importing this package registers every built-in rule type.
"""

from . import (  # noqa: F401
    custom,
    dates,
    duplicates,
    missing,
    numbers,
    strings,
    types,
    units,
)
from .base import CleaningRule, RuleOutcome, build_rules, registry_types  # noqa: F401
