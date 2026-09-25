"""Error classifier for distinguishing retryable from fatal conditions."""

from __future__ import annotations

import logging
from core.errors import ErrorCategory, classify_error

log = logging.getLogger("engines.recovery.error_classifier")

RETRYABLE_CATEGORIES: set[ErrorCategory] = {
    ErrorCategory.RATE_LIMIT,
    ErrorCategory.TRANSIENT,
    ErrorCategory.DATABASE,
}

NON_RETRYABLE_CATEGORIES: set[ErrorCategory] = {
    ErrorCategory.PERMISSION,
    ErrorCategory.HIERARCHY,
    ErrorCategory.INVALID_INPUT,
    ErrorCategory.NOT_FOUND,
}


def is_retryable(exc: BaseException) -> bool:
    """Return True if an exception is safe and worthwhile to retry."""
    category = classify_error(exc)
    return category in RETRYABLE_CATEGORIES
