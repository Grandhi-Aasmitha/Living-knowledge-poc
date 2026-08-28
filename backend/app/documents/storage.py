import hashlib
from pathlib import Path, PurePath

from app.config import REPOSITORY_ROOT
from app.documents.parsers import UnsupportedDocumentTypeError, is_supported_filename


class UploadTooLargeError(ValueError):
    pass


def safe_original_filename(filename: str) -> str:
    name = PurePath(filename.replace(chr(92), "/")).name.strip()
    if name in {"", ".", ".."}:
        raise UnsupportedDocumentTypeError("Uploaded file must have a valid filename")
    return name


class DocumentStorage:
    def __init__(self, upload_directory: str, max_upload_size_mb: int) -> None:
        configured_root = Path(upload_directory)
        self._upload_root = (configured_root if configured_root.is_absolute() else REPOSITORY_ROOT / configured_root).resolve()
        self._storage_prefix = upload_directory.replace(chr(92), "/").strip("/")
        self._max_bytes = max_upload_size_mb * 1024 * 1024

    def validate_size(self, content: bytes) -> None:
        if len(content) > self._max_bytes:
            raise UploadTooLargeError(f"Uploaded file exceeds the {self._max_bytes // (1024 * 1024)} MB Phase 4 limit")

    def content_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def save(self, content: bytes, original_filename: str, content_hash: str) -> tuple[str, Path]:
        filename = safe_original_filename(original_filename)
        if not is_supported_filename(filename):
            raise UnsupportedDocumentTypeError("Unsupported file type. Supported types: .pdf, .docx, .pptx, .txt, .md")
        extension = Path(filename).suffix.casefold()
        self._upload_root.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{content_hash}{extension}"
        path = (self._upload_root / stored_filename).resolve()
        if self._upload_root != path.parent:
            raise UnsupportedDocumentTypeError("Uploaded file path is invalid")
        path.write_bytes(content)
        relative_key = f"{self._storage_prefix}/{stored_filename}"
        return relative_key, path
