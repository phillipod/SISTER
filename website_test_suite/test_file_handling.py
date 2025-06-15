import pytest
import os
from io import BytesIO
from unittest.mock import patch, MagicMock
from sister_website.models import User, Submission, Build, Screenshot, db, AcceptanceState
from PIL import Image


def create_test_image_data(width=100, height=100, format='PNG'):
    """Create test image data."""
    img = Image.new('RGB', (width, height), color='red')
    img_buffer = BytesIO()
    img.save(img_buffer, format=format)
    return img_buffer.getvalue()


def create_test_submission_with_screenshot(app, email="test@example.com"):
    """Helper to create a submission with screenshot for testing."""
    with app.app_context():
        submission = Submission(
            email=email,
            acceptance_token='test_token_123',
            acceptance_state=AcceptanceState.ACCEPTED
        )
        
        build = Build(submission=submission, platform='PC', type='space')
        
        screenshot_data = create_test_image_data()
        screenshot = Screenshot(
            build=build,
            filename='test_screenshot.png',
            md5sum='test_md5_hash',
            data=screenshot_data
        )
        
        db.session.add_all([submission, build, screenshot])
        db.session.commit()
        return submission, screenshot


def create_and_login_user(client, app, email="testuser@example.com"):
    """Helper to create and login a user."""
    with app.app_context():
        user = User(email=email)
        user.set_password('password123')
        user.email_verified = True
        db.session.add(user)
        db.session.commit()
    
    # Login
    client.post('/login', data={
        'email': email,
        'password': 'password123',
        'csrf_token': 'test'
    }, follow_redirects=True)
    
    return user


def test_admin_screenshot_route_success(client, app, admin_user):
    """Test admin screenshot serving route."""
    submission, screenshot = create_test_submission_with_screenshot(app)
    
    # Login as admin
    client.post('/admin/login', data={
        'username': admin_user.username,
        'password': 'adminpass',
        'csrf_token': 'test'
    })
    
    with app.app_context():
        response = client.get(f'/screenshot/{screenshot.id}')
        assert response.status_code == 200
        assert response.headers['Content-Type'] == 'image/png'
        assert len(response.data) > 0


def test_admin_screenshot_route_not_found(client, app, admin_user):
    """Test admin screenshot serving route with non-existent screenshot."""
    # Login as admin
    client.post('/admin/login', data={
        'username': admin_user.username,
        'password': 'adminpass',
        'csrf_token': 'test'
    })
    
    response = client.get('/screenshot/nonexistent-id')
    assert response.status_code == 404


def test_admin_screenshot_route_unauthorized(client, app):
    """Test admin screenshot serving route without admin access."""
    submission, screenshot = create_test_submission_with_screenshot(app)
    
    with app.app_context():
        response = client.get(f'/screenshot/{screenshot.id}')
        assert response.status_code == 302  # Redirect to admin login


def test_user_screenshot_route_success(client, app):
    """Test user screenshot serving route for own submissions."""
    user = create_and_login_user(client, app, "user@example.com")
    submission, screenshot = create_test_submission_with_screenshot(app, "user@example.com")
    
    with app.app_context():
        response = client.get(f'/me/screenshot/{screenshot.id}')
        assert response.status_code == 200
        assert response.headers['Content-Type'] == 'image/png'
        assert len(response.data) > 0


def test_user_screenshot_route_unauthorized_different_user(client, app):
    """Test user screenshot serving route for another user's submission."""
    create_and_login_user(client, app, "user1@example.com")
    submission, screenshot = create_test_submission_with_screenshot(app, "user2@example.com")  # Different user
    
    with app.app_context():
        response = client.get(f'/me/screenshot/{screenshot.id}')
        assert response.status_code == 403  # Forbidden


def test_user_screenshot_route_not_found(client, app):
    """Test user screenshot serving route with non-existent screenshot."""
    create_and_login_user(client, app)
    
    response = client.get('/me/screenshot/nonexistent-id')
    assert response.status_code == 404


def test_user_screenshot_route_requires_login(client, app):
    """Test user screenshot route requires authentication."""
    submission, screenshot = create_test_submission_with_screenshot(app)
    
    with app.app_context():
        response = client.get(f'/me/screenshot/{screenshot.id}')
        assert response.status_code == 302  # Redirect to login


def test_screenshot_thumbnail_generation(app):
    """Test screenshot thumbnail generation functionality."""
    # Test with valid PNG data
    png_data = create_test_image_data(800, 600, 'PNG')
    
    with app.app_context():
        from sister_website.app import generate_screenshot_thumbnail
        thumbnail = generate_screenshot_thumbnail(png_data)
        
        assert thumbnail is not None
        assert len(thumbnail) > 0
        
        # Verify thumbnail is a valid JPEG
        thumbnail_img = Image.open(BytesIO(thumbnail))
        assert thumbnail_img.format == 'JPEG'
        assert thumbnail_img.size[0] <= 240  # Max width
        assert thumbnail_img.size[1] <= 240  # Max height


def test_screenshot_thumbnail_generation_rgba(app):
    """Test screenshot thumbnail generation with RGBA image."""
    # Create RGBA image
    img = Image.new('RGBA', (400, 300), color=(255, 0, 0, 128))
    img_buffer = BytesIO()
    img.save(img_buffer, format='PNG')
    rgba_data = img_buffer.getvalue()
    
    with app.app_context():
        from sister_website.app import generate_screenshot_thumbnail
        thumbnail = generate_screenshot_thumbnail(rgba_data)
        
        assert thumbnail is not None
        # Should convert to RGB successfully
        thumbnail_img = Image.open(BytesIO(thumbnail))
        assert thumbnail_img.format == 'JPEG'
        assert thumbnail_img.mode == 'RGB'


def test_screenshot_thumbnail_generation_invalid_data(app):
    """Test screenshot thumbnail generation with invalid image data."""
    invalid_data = b"not an image"
    
    with app.app_context():
        from sister_website.app import generate_screenshot_thumbnail
        thumbnail = generate_screenshot_thumbnail(invalid_data)
        
        assert thumbnail is None


def test_allowed_mime_type_validation(app):
    """Test MIME type validation for file uploads."""
    with app.app_context():
        from sister_website.app import allowed_mime
        
        # Create a valid PNG file
        png_data = create_test_image_data()
        png_file = BytesIO(png_data)
        png_file.filename = 'test.png'
        
        # Create a valid JPEG file
        jpeg_data = create_test_image_data(format='JPEG')
        jpeg_file = BytesIO(jpeg_data)
        jpeg_file.filename = 'test.jpg'
        
        # Create invalid file
        invalid_file = BytesIO(b"not an image")
        invalid_file.filename = 'test.txt'
        
        # Mock the magic library
        with patch('magic.from_buffer') as mock_magic:
            mock_magic.return_value = 'image/png'
            result = allowed_mime(png_file)
            assert result == 'image/png'
            
            mock_magic.return_value = 'image/jpeg'
            result = allowed_mime(jpeg_file)
            assert result == 'image/jpeg'
            
            mock_magic.return_value = 'text/plain'
            result = allowed_mime(invalid_file)
            assert result is None


def test_allowed_mime_type_validation_exception(app):
    """Test MIME type validation when magic library throws exception."""
    with app.app_context():
        from sister_website.app import allowed_mime
        
        test_file = BytesIO(b"test data")
        test_file.filename = 'test.png'
        
        with patch('magic.from_buffer', side_effect=Exception("Magic error")):
            result = allowed_mime(test_file)
            assert result is None


def test_allowed_mime_type_validation_import_error(app):
    """Test MIME type validation when magic library is not available."""
    with app.app_context():
        from sister_website.app import allowed_mime
        
        test_file = BytesIO(b"test data")
        test_file.filename = 'test.png'
        
        with patch('magic.from_buffer', side_effect=ImportError("No magic")):
            result = allowed_mime(test_file)
            assert result is None


def test_save_screenshot_function_success(app):
    """Test save_screenshot utility function success case."""
    with app.app_context():
        from sister_website.app import save_screenshot
        
        # Create test submission and build
        submission = Submission(
            email='test@example.com',
            acceptance_token='token123',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        db.session.add_all([submission, build])
        db.session.commit()
        
        # Create valid image file
        image_data = create_test_image_data()
        image_file = BytesIO(image_data)
        image_file.filename = 'test.png'
        
        # Mock allowed_mime to return valid MIME type
        with patch('sister_website.app.allowed_mime', return_value='image/png'):
            result = save_screenshot(image_file, build.id, 'test.png')
            
            assert result is True
            
            # Verify screenshot was saved to database
            screenshot = Screenshot.query.filter_by(build_id=build.id).first()
            assert screenshot is not None
            assert screenshot.filename == 'test.png'
            assert len(screenshot.data) > 0


def test_save_screenshot_function_invalid_mime(app):
    """Test save_screenshot utility function with invalid MIME type."""
    with app.app_context():
        from sister_website.app import save_screenshot
        
        # Create test submission and build
        submission = Submission(
            email='test@example.com',
            acceptance_token='token123',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        db.session.add_all([submission, build])
        db.session.commit()
        
        # Create invalid file
        invalid_file = BytesIO(b"not an image")
        invalid_file.filename = 'bad.txt'
        
        # Mock allowed_mime to return None (invalid)
        with patch('sister_website.app.allowed_mime', return_value=None):
            result = save_screenshot(invalid_file, build.id, 'bad.txt')
            
            assert result is False
            
            # Verify no screenshot was saved
            screenshot = Screenshot.query.filter_by(build_id=build.id).first()
            assert screenshot is None


def test_save_screenshot_function_duplicate_md5(app):
    """Test save_screenshot utility function with duplicate MD5 hash."""
    with app.app_context():
        from sister_website.app import save_screenshot
        
        # Create test submission and build
        submission = Submission(
            email='test@example.com',
            acceptance_token='token123',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        
        # Create existing screenshot with same MD5
        existing_screenshot = Screenshot(
            build=build,
            filename='existing.png',
            md5sum='duplicate_hash',
            data=b'existing data'
        )
        
        db.session.add_all([submission, build, existing_screenshot])
        db.session.commit()
        
        # Try to save another screenshot that would have same MD5
        image_file = BytesIO(b"test image data")
        image_file.filename = 'duplicate.png'
        
        with patch('sister_website.app.allowed_mime', return_value='image/png'):
            with patch('hashlib.md5') as mock_md5:
                mock_md5.return_value.hexdigest.return_value = 'duplicate_hash'
                
                result = save_screenshot(image_file, build.id, 'duplicate.png')
                
                assert result is False
                
                # Verify only one screenshot exists
                screenshots = Screenshot.query.filter_by(build_id=build.id).all()
                assert len(screenshots) == 1
                assert screenshots[0].filename == 'existing.png'


def test_file_upload_size_limit(client, app):
    """Test file upload size limit enforcement."""
    # This would typically be tested by trying to upload a file larger than MAX_CONTENT_LENGTH
    # For now, we'll test that the configuration is set
    assert app.config.get('MAX_CONTENT_LENGTH') == 32 * 1024 * 1024  # 32MB


def test_secure_filename_usage(app):
    """Test that secure filename is used for file uploads."""
    with app.app_context():
        from werkzeug.utils import secure_filename
        
        # Test various filename scenarios
        assert secure_filename('test.png') == 'test.png'
        assert secure_filename('../../../etc/passwd') == 'etc_passwd'
        assert secure_filename('file with spaces.png') == 'file_with_spaces.png'
        assert secure_filename('файл.png') == '.png'  # Non-ASCII characters removed 