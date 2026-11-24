"""Fernet encryption. The key file lives in its own Docker volume, apart from the SQLite file."""
import os
from pathlib import Path

from cryptography.fernet import Fernet


class SecretBox:
    def __init__(self, key_path):
        p = Path(key_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(Fernet.generate_key())
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        self._f = Fernet(p.read_bytes())

    def encrypt(self, plain: str) -> str:
        return self._f.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._f.decrypt(token.encode()).decode()
