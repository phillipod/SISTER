"""
Exceptions for the ForwardEmail API client.
"""

class ForwardEmailError(Exception):
    """Base exception for all ForwardEmail API errors."""
    pass


class AuthenticationError(ForwardEmailError):
    """Raised when authentication fails with the API."""
    pass


class APIError(ForwardEmailError):
    """Raised when the API returns an error response."""
    def __init__(self, message, status_code=None, response=None):
        self.status_code = status_code
        self.response = response
        super().__init__(message)


class RateLimitError(APIError):
    """Raised when the rate limit is exceeded."""
    pass


class ValidationError(ForwardEmailError):
    """Raised when input validation fails."""
    pass
