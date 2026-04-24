"""测试安全模块"""

import pytest
from app.core.security import hash_password, verify_password, create_access_token, decode_access_token


def test_hash_password():
    hashed = hash_password("testpassword123")
    assert hashed != "testpassword123"
    assert hashed.startswith("$2b$")  # bcrypt prefix


def test_verify_password_correct():
    plain = "mypassword"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("correct")
    assert verify_password("wrong", hashed) is False


def test_hash_uniqueness():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


def test_access_token_roundtrip():
    token = create_access_token(subject="42")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert "exp" in payload


def test_access_token_decode_fail():
    with pytest.raises(Exception):
        decode_access_token("invalid.token.here")


def test_schema_validation():
    """测试请求/响应 Schema 验证"""
    from app.schemas.auth import LoginRequest, RegisterRequest
    from pydantic import ValidationError

    # 有效数据
    login = LoginRequest(username="testuser", password="password123")
    assert login.username == "testuser"

    register = RegisterRequest(username="testuser", email="test@example.com", password="password123")
    assert register.email == "test@example.com"

    # 无效数据 - 密码太短
    with pytest.raises(ValidationError):
        LoginRequest(username="ab", password="password123")

    # 无效邮箱
    with pytest.raises(ValidationError):
        RegisterRequest(username="test", email="not-email", password="password123")
