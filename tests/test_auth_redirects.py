import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth_redirects.db")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")

from app.models import User
from app.routers.auth import _registration_complete, github_callback


def test_github_callback_without_code_redirects_to_login():
    response = github_callback(request=None, code=None, error=None, db=None)

    assert response.status_code == 302
    assert "auth_error=github_authorization_cancelled" in response.headers["location"]


def test_github_callback_with_github_error_redirects_to_login():
    response = github_callback(request=None, code=None, error="access_denied", db=None)

    assert response.status_code == 302
    assert "auth_error=github_authorization_cancelled" in response.headers["location"]


def test_registration_is_incomplete_until_required_profile_fields_exist():
    user = User(
        github_id="123",
        username="newstudent",
        avatar_url="https://example.com/avatar.png",
    )

    assert _registration_complete(user) is False

    user.display_name = "New Student"
    user.student_id = "2024-0001"
    user.program = "BSCS"
    user.year_level = "1st Year"

    assert _registration_complete(user) is True
