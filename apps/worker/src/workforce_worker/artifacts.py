"""Task deliverables (reports, lists, prepared bookings)."""

import csv
import hashlib
import io
import re

from psycopg import AsyncConnection

CONTENT_TYPES = {
    "csv": "text/csv",
    "markdown": "text/markdown",
    "json": "application/json",
    "html": "text/html",
    "css": "text/css",
    "js": "text/javascript",
    "txt": "text/plain",
    "svg": "image/svg+xml",
    "jpg": "image/jpeg",
    "png": "image/png",
}
EXTENSIONS = {
    "csv": "csv",
    "markdown": "md",
    "json": "json",
    "html": "html",
    "css": "css",
    "js": "js",
    "txt": "txt",
    "svg": "svg",
    "jpg": "jpg",
    "png": "png",
}
BINARY = {"jpg", "png"}
MAX_BYTES = 5 * 1024 * 1024


def safe_name(name: str, fmt: str) -> str:
    """A flat, safe file name that keeps names like index.html or styles.css intact."""
    base = name.replace("\\", "/").split("/")[-1]  # never a path
    stem = re.sub(r"[^\w\-. ]+", "", base).strip().replace(" ", "_").strip(".")[:80] or "report"
    ext = EXTENSIONS[fmt]
    return stem if stem.lower().endswith("." + ext) else f"{stem}.{ext}"


def csv_stats(text: str) -> tuple[int, list[str]]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return 0, []
    return len(rows) - 1, rows[0]


async def save_artifact(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    task_id: str,
    step_id: str | None,
    name: str,
    fmt: str,
    content: str = "",
    data: bytes | None = None,
) -> dict:
    """Save a deliverable: text `content`, or raw `data` for images."""
    if fmt not in CONTENT_TYPES:
        raise ValueError(f"unsupported format {fmt!r}")
    if fmt in BINARY and data is None:
        raise ValueError(f"{fmt} files need image data")
    data = data if data is not None else content.encode()
    if len(data) > MAX_BYTES:
        raise ValueError("file is larger than 5 MB")
    filename = safe_name(name, fmt)
    row = await (
        await conn.execute(
            """insert into public.artifacts
                   (workspace_id, task_id, step_id, name, storage_uri, file_type,
                    checksum_sha256, size_bytes, content, preview)
               values (%s, %s, %s, %s, 'inline', %s, %s, %s, %s, %s)
               returning id::text""",
            (
                workspace_id,
                task_id,
                step_id,
                filename,
                CONTENT_TYPES[fmt],
                hashlib.sha256(data).hexdigest(),
                len(data),
                data,
                "[image]" if fmt in BINARY else content[:2000],
            ),
        )
    ).fetchone()
    return {"id": row["id"], "name": filename, "size_bytes": len(data)}
