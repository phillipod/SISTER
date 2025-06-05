# STO Screenshot Collection Website

A Flask-based web application for collecting Star Trek Online build screenshots with proper consent management.

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
Create a `.env` file with the following variables:
```
SECRET_KEY=your-secret-key-here
SENDGRID_API_KEY=your-sendgrid-api-key
FROM_EMAIL=your-verified-sender-email
```

4. Run the application:
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Features

- Screenshot upload with email collection
- Granular consent options for different data uses
- Automated email consent form sending
- Privacy-focused design
- Star Trek-inspired subtle UI

## Security Notes

- Make sure to change the SECRET_KEY in production
- Use HTTPS in production
- Configure proper file upload limits
- Set up proper email verification
- Implement rate limiting for production use

## License

This project is intended for community use. Not affiliated with Cryptic Studios or Perfect World Entertainment. 