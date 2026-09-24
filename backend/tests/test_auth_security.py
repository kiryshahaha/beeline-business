"""Unit tests for password hashing (Argon2) and JWT token operations."""

import logging
import unittest
from datetime import timedelta
from unittest.mock import patch

import jwt
from pydantic import SecretStr, ValidationError

from app.core.access_log import AccessLogRedactionFilter
from app.core.config import Settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)


class AuthSecurityTests(unittest.TestCase):
    def test_jwt_secret_is_required_and_must_have_at_least_32_bytes(self):
        with patch.dict(
            "os.environ", {"DATABASE_URL": "postgresql://user:pass@localhost/db"}, clear=True
        ):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)
            with self.assertRaises(ValidationError):
                Settings(
                    _env_file=None,
                    database_url="postgresql://user:pass@localhost/db",
                    jwt_secret_key="too-short",
                )

        settings = Settings(
            _env_file=None,
            database_url="postgresql://user:pass@localhost/db",
            jwt_secret_key="valid-test-signing-secret-with-more-than-32-bytes",
        )
        self.assertIsInstance(settings.jwt_secret_key, SecretStr)
        self.assertNotIn(settings.jwt_secret_key.get_secret_value(), repr(settings.jwt_secret_key))

    def test_access_log_filter_redacts_calendar_bearer_query_value(self):
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "server.py",
            1,
            '%s - "%s %s HTTP/%s" %d',
            (
                "127.0.0.1",
                "GET",
                "/api/v1/schedule/calendar.ics?token=secret-feed-value",
                "1.1",
                200,
            ),
            None,
        )

        AccessLogRedactionFilter().filter(record)

        self.assertNotIn("secret-feed-value", record.getMessage())
        self.assertIn("[REDACTED]", record.getMessage())

    def test_argon2_password_hashing_and_verification(self):
        password = "SecurePassword123!"
        hashed = hash_password(password)

        self.assertNotEqual(password, hashed)
        self.assertTrue(hashed.startswith("$argon2"))
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("WrongPassword123!", hashed))
        self.assertFalse(verify_password(password, "invalid_hash_string"))

    def test_token_hash_produces_consistent_sha256(self):
        token = "test-token-string"
        hash_1 = hash_token(token)
        hash_2 = hash_token(token)

        self.assertEqual(hash_1, hash_2)
        self.assertEqual(len(hash_1), 64)

    def test_jwt_access_token_creation_and_decoding(self):
        payload = {"sub": "42", "username": "test_user", "role": "observer"}
        token = create_access_token(payload)

        decoded = decode_token(token)
        self.assertEqual(decoded["sub"], "42")
        self.assertEqual(decoded["username"], "test_user")
        self.assertEqual(decoded["role"], "observer")
        self.assertEqual(decoded["type"], "access")
        self.assertIn("exp", decoded)
        self.assertIn("iat", decoded)

    def test_jwt_refresh_token_creation_and_decoding(self):
        payload = {"sub": "42", "username": "test_user", "role": "worker"}
        token, expires_at = create_refresh_token(payload)

        decoded = decode_token(token)
        self.assertEqual(decoded["sub"], "42")
        self.assertEqual(decoded["type"], "refresh")
        self.assertIn("jti", decoded)

    def test_jwt_expired_token_raises_error(self):
        payload = {"sub": "1"}
        token = create_access_token(payload, expires_delta=timedelta(seconds=-1))

        with self.assertRaises(jwt.ExpiredSignatureError):
            decode_token(token)
