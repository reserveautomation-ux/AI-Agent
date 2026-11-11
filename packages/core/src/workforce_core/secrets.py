"""Encryption for connected-account credentials (OAuth tokens).

AES-256-GCM with a key that only the API and worker hold (env
TOKEN_ENCRYPTION_KEY). Each ciphertext is bound to its workspace and provider
("associated data"), so a stolen or swapped row can't be decrypted in another
context. The database only ever stores ciphertext.

Generate a key with:  python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
"""

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg import AsyncConnection

_VERSION = b"\x01"


class SecretError(Exception):
    pass


class SecretBox:
    def __init__(self, key_b64: str):
        try:
            key = base64.b64decode(key_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise SecretError("TOKEN_ENCRYPTION_KEY must be base64") from exc
        if len(key) != 32:
            raise SecretError("TOKEN_ENCRYPTION_KEY must decode to 32 bytes")
        self._aead = AESGCM(key)

    @classmethod
    def from_env(cls) -> "SecretBox | None":
        key = os.environ.get("TOKEN_ENCRYPTION_KEY")
        return cls(key) if key else None

    def encrypt(self, data: dict[str, Any], context: str) -> bytes:
        nonce = os.urandom(12)
        plaintext = json.dumps(data, separators=(",", ":")).encode()
        return _VERSION + nonce + self._aead.encrypt(nonce, plaintext, context.encode())

    def decrypt(self, blob: bytes, context: str) -> dict[str, Any]:
        blob = bytes(blob)
        if not blob.startswith(_VERSION) or len(blob) < 30:
            raise SecretError("unknown secret format")
        try:
            plaintext = self._aead.decrypt(blob[1:13], blob[13:], context.encode())
        except InvalidTag as exc:
            raise SecretError("could not decrypt (wrong key or context)") from exc
        return json.loads(plaintext)


def secret_context(workspace_id: str, provider: str) -> str:
    return f"workforce:{workspace_id}:{provider}"


async def store_secret(
    conn: AsyncConnection, box: SecretBox, *, workspace_id: str, provider: str, data: dict
) -> str:
    row = await (
        await conn.execute(
            "insert into public.connection_secrets (workspace_id, ciphertext)"
            " values (%s, %s) returning id::text",
            (workspace_id, box.encrypt(data, secret_context(workspace_id, provider))),
        )
    ).fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


async def update_secret(
    conn: AsyncConnection,
    box: SecretBox,
    *,
    secret_id: str,
    workspace_id: str,
    provider: str,
    data: dict,
) -> None:
    await conn.execute(
        "update public.connection_secrets set ciphertext = %s, updated_at = now()"
        " where id = %s and workspace_id = %s",
        (box.encrypt(data, secret_context(workspace_id, provider)), secret_id, workspace_id),
    )


async def load_secret(
    conn: AsyncConnection, box: SecretBox, *, secret_id: str, workspace_id: str, provider: str
) -> dict:
    row = await (
        await conn.execute(
            "select ciphertext from public.connection_secrets where id = %s and workspace_id = %s",
            (secret_id, workspace_id),
        )
    ).fetchone()
    if row is None:
        raise SecretError("secret not found")
    blob = row["ciphertext"] if isinstance(row, dict) else row[0]
    return box.decrypt(blob, secret_context(workspace_id, provider))
