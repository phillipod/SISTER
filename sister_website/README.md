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
# Token required to access admin-only endpoints
ADMIN_TOKEN=your-admin-token
# Example database connection for MySQL
# DATABASE_URL=mysql+pymysql://user:password@hostname/dbname
```

4. Run the application:
```bash
python app.py
```

The application will be available at `http://localhost:5000`

### Running on multiple nodes

Set `DATABASE_URL` to a MySQL connection string so all instances can share the
same database. Uploaded screenshots are also stored in the database as BLOBs,
allowing workers on different nodes to access them.

## Features

- Screenshot upload with email collection
- Granular consent options for different data uses
- Automated email consent form sending
- Privacy-focused design
- Star Trek-inspired subtle UI
- Admin screenshot browser organized by platform, type, and submission date

## Security Notes

- Make sure to change the SECRET_KEY in production
- Use HTTPS in production
- Configure proper file upload limits
- Uploaded files and the database are stored in the Flask instance folder
- Validate uploaded file types using python-magic
  - Requires the libmagic system package
- Set up proper email verification
- Implement rate limiting for production use

## License

This project is intended for community use. Not affiliated with Cryptic Studios or Perfect World Entertainment. 
