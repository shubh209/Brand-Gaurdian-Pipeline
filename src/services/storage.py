"""
Storage provider seam — put/get/delete/presign upload blobs by STORAGE_BACKEND.

Supabase Storage is the live backend. Added beside the worker's existing Azure Blob
calls; the worker + endpoints are rewired to use this in #13.

ponytail: one module-level Supabase client. Bucket must exist (create it once in the
Supabase dashboard or via the service-role key). Object keys are relative paths within
the bucket, e.g. "uploads/<audit_id>.mp4".
"""
import tempfile
import threading

from src.config import config

_BUCKET = "uploads"
_client = None
_lock = threading.Lock()


def _supabase():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from supabase import create_client
                # Server-side storage needs the service-role key (bypasses RLS). The
                # publishable key is RLS-gated and 403s on private-bucket writes.
                key = config.SUPABASE_SERVICE_KEY or config.SUPABASE_KEY
                _client = create_client(config.SUPABASE_URL, key)
    return _client


def _bucket():
    return _supabase().storage.from_(_BUCKET)


def upload(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to `key`. Returns the storage key. Overwrites if present."""
    if config.STORAGE_BACKEND != "supabase":
        raise ValueError(f"Unsupported STORAGE_BACKEND: {config.STORAGE_BACKEND!r}")
    _bucket().upload(key, data, {"content-type": content_type, "upsert": "true"})
    return key


def download_to_temp(key: str, suffix: str = ".mp4") -> str:
    """Download `key` to a local temp file. Returns the temp path (caller deletes)."""
    data = _bucket().download(key)
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
    finally:
        tmp.close()
    return tmp.name


def delete(key: str) -> None:
    """Delete `key`. Best-effort; ignores if already gone."""
    try:
        _bucket().remove([key])
    except Exception:
        pass


def presign_upload(key: str) -> str:
    """A one-time signed URL the client uses to upload directly to `key`."""
    signed = _bucket().create_signed_upload_url(key)
    # SDK returns a dict; the URL key has varied across versions.
    return signed.get("signed_url") or signed.get("signedURL") or signed.get("url") or signed


def key_for_audit(audit_id: str) -> str:
    """Canonical storage key for an audit's uploaded video."""
    return f"uploads/{audit_id}.mp4"
