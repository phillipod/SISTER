"""
ForwardEmail API client implementation.
"""
import base64
import json
from typing import Any, Dict, List, Optional, Union, Tuple, TypeVar, Type, cast
import requests
from requests.adapters import HTTPAdapter, Retry
from urllib.parse import urljoin

from .models import EmailMessage, EmailAddress, EmailAttachment
from .exceptions import (
    ForwardEmailError,
    AuthenticationError,
    APIError,
    RateLimitError,
    ValidationError
)

T = TypeVar('T', bound='ForwardEmailClient')

class ForwardEmailClient:
    """Client for interacting with the ForwardEmail API."""

    BASE_URL = "https://api.forwardemail.net/v1/"
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        user_agent: Optional[str] = None
    ) -> None:
        """Initialize the ForwardEmail client.
        
        Args:
            api_key: Your ForwardEmail API key
            base_url: Base URL for the API (defaults to production)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            user_agent: Custom User-Agent string
        """
        if not api_key:
            raise ValueError("API key is required")
            
        self.api_key = api_key
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout
        self.session = self._create_session(max_retries)
        self.user_agent = user_agent or f"forwardemail-python/{self._get_version()}"
        
        # Set up session headers
        self.session.headers.update({
            'User-Agent': self.user_agent,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        
        # Set up basic auth with API key
        self.session.auth = (self.api_key, '')
    
    @classmethod
    def from_environment(cls: Type[T], env_prefix: str = "FORWARD_EMAIL_") -> T:
        """Create a client using environment variables.
        
        Looks for FORWARD_EMAIL_API_KEY by default.
        """
        import os
        
        api_key = os.getenv(f"{env_prefix}API_KEY")
        if not api_key:
            raise ValueError(
                f"Environment variable {env_prefix}API_KEY is not set. "
                "Please set it to your ForwardEmail API key."
            )
            
        return cls(api_key=api_key)
    
    def _create_session(self, max_retries: int) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
        )
        
        # Mount the retry adapter
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        return session
    
    def _get_version(self) -> str:
        """Get the package version."""
        from . import __version__
        return __version__
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make an API request with proper error handling."""
        url = urljoin(self.base_url, endpoint.lstrip('/'))
        
        # Set default timeout if not provided
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                **kwargs
            )
            
            # Handle error responses
            if response.status_code >= 400:
                self._handle_error_response(response)
                
            # For 204 No Content, return an empty dict
            if response.status_code == 204:
                return {}
                
            # Parse JSON response
            try:
                return response.json()
            except ValueError:
                return {"message": response.text}
                
        except requests.exceptions.RequestException as e:
            raise ForwardEmailError(f"Request failed: {str(e)}") from e
    
    def _handle_error_response(self, response: requests.Response) -> None:
        """Handle API error responses."""
        status_code = response.status_code
        
        try:
            error_data = response.json()
            message = error_data.get('message', 'Unknown error')
        except ValueError:
            message = response.text or 'Unknown error'
        
        if status_code == 400:
            raise ValidationError(f"Validation error: {message}")
        elif status_code == 401:
            raise AuthenticationError("Invalid API key or authentication failed")
        elif status_code == 403:
            raise AuthenticationError("Insufficient permissions")
        elif status_code == 404:
            raise APIError("Resource not found", status_code=status_code)
        elif status_code == 429:
            retry_after = response.headers.get('Retry-After', '60')
            raise RateLimitError(
                f"Rate limit exceeded. Try again in {retry_after} seconds.",
                status_code=status_code,
                response=response
            )
        elif 500 <= status_code < 600:
            raise APIError(
                f"Server error: {message}",
                status_code=status_code,
                response=response
            )
        else:
            raise APIError(
                f"Unexpected error: {message}",
                status_code=status_code,
                response=response
            )
    
    # Email methods
    
    def send_email(
        self,
        message: Union[EmailMessage, Dict[str, Any]],
        **kwargs
    ) -> Dict[str, Any]:
        """Send an email via the ForwardEmail API.
        
        Args:
            message: Either an EmailMessage instance or a dictionary with email parameters
            **kwargs: Additional parameters to pass to the API
            
        Returns:
            Dict containing the API response
            
        Example:
            ```python
            # Using EmailMessage
            message = EmailMessage(
                from_email="sender@example.com",
                to="recipient@example.com",
                subject="Hello",
                text="This is a test email"
            )
            client.send_email(message)
            
            # Using dict
            client.send_email({
                "from": "sender@example.com",
                "to": "recipient@example.com",
                "subject": "Hello",
                "text": "This is a test email"
            })
            ```
        """
        if isinstance(message, EmailMessage):
            data = message.to_dict()
        else:
            data = message
            
        # Update with any additional kwargs
        data.update(kwargs)
        
        return self._request('POST', 'emails', json_data=data)
    
    def get_email(self, email_id: str) -> Dict[str, Any]:
        """Retrieve details of a sent email.
        
        Args:
            email_id: The ID of the email to retrieve
            
        Returns:
            Dict containing the email details
        """
        return self._request('GET', f'emails/{email_id}')
    
    def list_emails(
        self,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        sort: Optional[str] = None,
        page: int = 1,
        limit: int = 10,
        **kwargs
    ) -> Dict[str, Any]:
        """List sent emails with optional filtering and pagination.
        
        Args:
            query: Search query to filter emails
            domain: Filter by domain
            sort: Sort field (prefix with - for descending)
            page: Page number (1-based)
            limit: Number of results per page (max 100)
            **kwargs: Additional query parameters
            
        Returns:
            Dict containing the paginated list of emails
        """
        params = {
            'q': query,
            'domain': domain,
            'sort': sort,
            'page': max(1, page),
            'limit': min(100, max(1, limit))
        }
        
        # Add any additional params from kwargs
        params.update({k: v for k, v in kwargs.items() if v is not None})
        
        return self._request('GET', 'emails', params=params)
    
    def get_email_limit(self) -> Dict[str, int]:
        """Get the current email sending limits.
        
        Returns:
            Dict with 'count' (emails sent today) and 'limit' (daily limit)
        """
        return self._request('GET', 'emails/limit')
