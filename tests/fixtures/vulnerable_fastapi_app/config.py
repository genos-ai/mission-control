"""Deliberately insecure configuration — hardcoded secrets.

CWE-798: Hardcoded credentials. Scanners should flag API_KEY and JWT_SECRET.
"""

# VULNERABILITY: Hardcoded API key — should use env var or vault
API_KEY = "sk-live-abc123def456ghi789jkl012mno345pqr678"

# VULNERABILITY: Weak JWT secret — easily brute-forced
JWT_SECRET = "password123"

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
