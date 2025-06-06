# ForwardEmail Python Client

A Python client library for the [ForwardEmail](https://forwardemail.net) API, providing a simple interface to send and manage emails.

## Installation

```bash
pip install git+https://github.com/yourusername/forwardemail-python.git
```

## Usage

### Basic Setup

```python
from forwardemail import ForwardEmailClient

# Initialize the client with your API key
client = ForwardEmailClient(api_key="your_api_key_here")

# Or initialize from environment variable FORWARD_EMAIL_API_KEY
# client = ForwardEmailClient.from_environment()
```

### Sending an Email

#### Using EmailMessage class (recommended)

```python
from forwardemail import EmailMessage, EmailAddress

# Create a message
message = EmailMessage(
    from_email=EmailAddress("sender@example.com", "Sender Name"),
    to=["recipient@example.com", "another@example.com"],
    cc=["cc@example.com"],
    subject="Hello from ForwardEmail",
    text="This is a test email sent using the ForwardEmail Python client.",
    html="<strong>This is a test email</strong> sent using the ForwardEmail Python client."
)

# Send the email
response = client.send_email(message)
print(f"Email sent! Message ID: {response.get('id')}")
```

#### Using a dictionary

```python
email_data = {
    "from": "sender@example.com",
    "to": "recipient@example.com",
    "subject": "Hello from ForwardEmail",
    "text": "This is a test email sent using the ForwardEmail Python client.",
    "html": "<strong>This is a test email</strong> sent using the ForwardEmail Python client."
}

response = client.send_email(email_data)
print(f"Email sent! Message ID: {response.get('id')}")
```

### Retrieving Email Information

```python
# Get details of a sent email
email_id = "abc123xyz"  # Replace with an actual email ID
email_details = client.get_email(email_id)
print(f"Email subject: {email_details.get('subject')}")

# List sent emails with pagination
emails = client.list_emails(
    query="important",  # Optional search query
    page=1,
    limit=10
)
print(f"Found {len(emails.get('data', []))} emails")
```

### Checking Email Limits

```python
limits = client.get_email_limit()
print(f"Used {limits.get('count')} out of {limits.get('limit')} daily emails")
```

## Error Handling

The library raises specific exceptions for different types of errors:

```python
from forwardemail import (
    ForwardEmailError,
    AuthenticationError,
    APIError,
    RateLimitError,
    ValidationError
)

try:
    # Your API calls here
    pass
except AuthenticationError as e:
    print(f"Authentication failed: {e}")
except RateLimitError as e:
    print(f"Rate limit exceeded: {e}")
except ValidationError as e:
    print(f"Invalid input: {e}")
except APIError as e:
    print(f"API error: {e}")
except ForwardEmailError as e:
    print(f"Error: {e}")
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT
