"""
Example script demonstrating how to use the ForwardEmail Python client to send an email.
"""
import os
from dotenv import load_dotenv
from forwardemail import ForwardEmailClient, EmailMessage, EmailAddress

# Load environment variables from .env file
load_dotenv()

def send_simple_email():
    """Send a simple email using the ForwardEmail API."""
    # Initialize the client with API key from environment variable
    api_key = os.getenv('FORWARD_EMAIL_API_KEY')
    if not api_key:
        print("Error: FORWARD_EMAIL_API_KEY environment variable is not set.")
        print("Please set it in a .env file or pass it directly.")
        return
    
    client = ForwardEmailClient(api_key=api_key)
    
    # Create a simple email message
    message = EmailMessage(
        from_email=EmailAddress("sender@yourdomain.com", "Sender Name"),
        to=["recipient@example.com"],
        subject="Hello from ForwardEmail Python Client",
        text="This is a test email sent using the ForwardEmail Python client.",
        html="""
        <h1>Hello from ForwardEmail!</h1>
        <p>This is a test email sent using the <strong>ForwardEmail Python client</strong>.</p>
        <p>You can include <a href="https://forwardemail.net">links</a> and other HTML content.</p>
        """
    )
    
    try:
        # Send the email
        response = client.send_email(message)
        print(f"Email sent successfully! Message ID: {response.get('id', 'N/A')}")
        
        # Check email limits
        limits = client.get_email_limit()
        print(f"Email usage: {limits.get('count', 0)}/{limits.get('limit', 0)} emails sent today")
        
    except Exception as e:
        print(f"Error sending email: {e}")

if __name__ == "__main__":
    send_simple_email()
