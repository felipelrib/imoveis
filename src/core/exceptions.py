"""Custom application exceptions.

All application-specific exceptions should be defined or re-exported here
so that middleware, tasks, and callers can catch them uniformly.
"""

from __future__ import annotations


class AppException(Exception):
    """Base exception for all application errors."""

    default_message: str = "An application error occurred."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class ConfigError(AppException):
    """Raised when the application configuration is invalid."""

    default_message = "Invalid application configuration."


class DeduplicationError(AppException):
    """Raised when deduplication operations fail."""

    default_message = "Deduplication operation failed."


class PipelineError(AppException):
    """Raised when a processing pipeline step fails."""

    default_message = "Pipeline step failed."


class ScraperError(AppException):
    """Raised when a scraper encounters a fatal error."""

    default_message = "Scraper encountered an error."


class APIError(AppException):
    """Raised by API endpoints to signal client errors."""

    default_message = "API request failed."

    def __init__(self, message: str | None = None, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class CircuitBreakerOpenError(ScraperError):
    """Raised when the circuit breaker is open and the request is blocked."""

    default_message = "Circuit breaker is open — backing off."
