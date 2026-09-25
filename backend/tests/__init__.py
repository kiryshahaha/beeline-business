"""Backend tests."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-signing-key-which-is-over-32-bytes")
