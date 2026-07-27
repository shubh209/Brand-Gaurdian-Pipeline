"""
Typed error hierarchy for Brand Guardian pipeline.
Every module raises one of these — callers decide retry vs. dead-letter based on type.
"""


class BrandGuardianError(Exception):
    """Base for all project errors."""
    pass


class RetryableError(BrandGuardianError):
    """Transient failure (network timeout, rate limit, cold start). Worker should retry."""
    pass


class PermanentError(BrandGuardianError):
    """Unrecoverable failure (bad input, auth denied, logic error). Send to dead-letter."""
    pass


class ValidationError(PermanentError):
    """Input validation failure (bad MIME, missing audio, prompt injection detected)."""
    pass
