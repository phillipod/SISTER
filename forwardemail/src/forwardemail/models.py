"""
Data models for the ForwardEmail API.
"""
from typing import List, Optional, Union, Dict, Any
from dataclasses import dataclass, field, asdict
from email.utils import formataddr


@dataclass
class EmailAddress:
    """Represents an email address with an optional display name."""
    email: str
    name: Optional[str] = None

    def __str__(self) -> str:
        """Convert to string in format 'Name <email@example.com>'."""
        return formataddr((self.name, self.email)) if self.name else self.email

    @classmethod
    def from_string(cls, email_str: str) -> 'EmailAddress':
        """Create an EmailAddress from a string in 'Name <email@example.com>' format."""
        # Simple implementation - for more robust parsing, consider using email.utils.parseaddr
        if '<' in email_str and '>' in email_str:
            name_part = email_str.split('<')[0].strip()
            email_part = email_str.split('<')[1].split('>')[0].strip()
            return cls(email=email_part, name=name_part if name_part else None)
        return cls(email=email_str.strip())


@dataclass
class EmailAttachment:
    """Represents an email attachment."""
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"
    content_id: Optional[str] = None
    disposition: str = "attachment"  # or 'inline'
    headers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary suitable for the API."""
        return {
            'filename': self.filename,
            'content': self.content,
            'contentType': self.content_type,
            'cid': self.content_id,
            'contentDisposition': self.disposition,
            'headers': self.headers
        }


@dataclass
class EmailMessage:
    """Represents an email message to be sent."""
    from_email: Union[str, EmailAddress]
    to: Union[str, List[Union[str, EmailAddress]]]
    subject: str
    text: Optional[str] = None
    html: Optional[str] = None
    cc: Optional[Union[str, List[Union[str, EmailAddress]]]] = None
    bcc: Optional[Union[str, List[Union[str, EmailAddress]]]] = None
    reply_to: Optional[Union[str, EmailAddress]] = None
    in_reply_to: Optional[str] = None
    references: Optional[Union[str, List[str]]] = None
    attachments: List[EmailAttachment] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    priority: Optional[str] = None  # 'high', 'normal', 'low'
    message_id: Optional[str] = None
    date: Optional[str] = None  # ISO 8601 format

    def to_dict(self) -> Dict[str, Any]:
        """Convert the email message to a dictionary for the API."""
        def process_email_address(email):
            if isinstance(email, EmailAddress):
                return str(email)
            return email

        def process_email_list(emails):
            if isinstance(emails, str):
                return emails
            return [process_email_address(e) for e in emails] if emails else None

        data = {
            'from': process_email_address(self.from_email),
            'to': process_email_list(self.to),
            'subject': self.subject,
        }

        if self.text:
            data['text'] = self.text
        if self.html:
            data['html'] = self.html
        if self.cc:
            data['cc'] = process_email_list(self.cc)
        if self.bcc:
            data['bcc'] = process_email_list(self.bcc)
        if self.reply_to:
            data['replyTo'] = process_email_address(self.reply_to)
        if self.in_reply_to:
            data['inReplyTo'] = self.in_reply_to
        if self.references:
            data['references'] = self.references
        if self.attachments:
            data['attachments'] = [a.to_dict() for a in self.attachments]
        if self.headers:
            data['headers'] = self.headers
        if self.priority:
            data['priority'] = self.priority
        if self.message_id:
            data['messageId'] = self.message_id
        if self.date:
            data['date'] = self.date

        return data
