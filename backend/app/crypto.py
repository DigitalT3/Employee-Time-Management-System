"""Token helpers: HMAC lookup hashes and Fernet encryption for QR credentials (DEC-03)."""
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from app.config import get_settings


# PUBLIC_INTERFACE
def new_token() -> str:
    """Generate a 32-byte URL-safe random token."""
    return secrets.token_urlsafe(32)


# PUBLIC_INTERFACE
def token_hash(token: str) -> str:
    """Return the HMAC-SHA256 hex digest used to look up a token without storing it in clear."""
    key = get_settings().SECRET_KEY.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


# PUBLIC_INTERFACE
def encrypt_token(token: str) -> str:
    """Encrypt a token so a reprint can return the identical payload."""
    return Fernet(get_settings().FERNET_KEY.encode()).encrypt(token.encode()).decode()


# PUBLIC_INTERFACE
def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token previously produced by encrypt_token."""
    return Fernet(get_settings().FERNET_KEY.encode()).decrypt(ciphertext.encode()).decode()
