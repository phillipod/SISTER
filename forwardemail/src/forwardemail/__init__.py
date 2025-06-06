"""
ForwardEmail Python SDK - A simple client for the ForwardEmail API.
"""

from .client import ForwardEmailClient
from .models import EmailMessage, EmailAddress, EmailAttachment
from .exceptions import ForwardEmailError, AuthenticationError, APIError, RateLimitError, ValidationError

__version__ = '0.1.0'
__all__ = [
    'ForwardEmailClient',
    'EmailMessage',
    'EmailAddress',
    'EmailAttachment',
    'ForwardEmailError',
    'AuthenticationError',
    'APIError',
    'RateLimitError',
    'ValidationError'
]
