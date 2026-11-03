"""Private filesystem storage and content validation for Action Item evidence."""

import csv
import hashlib
import os
import re
import stat
import unicodedata
import uuid
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from zlib import error as ZlibError

MAX_EVIDENCE_FILE_BYTES = 10 * 1024 * 1024
_MAX_OOXML_ENTRIES = 1_000
_MAX_OOXML_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_OOXML_COMPRESSION_RATIO = 200
_STORAGE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".txt": "text/plain",
}
_OOXML_PARTS = {
    ".docx": (
        "word/document.xml",
        "document",
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ),
    ".xlsx": (
        "xl/workbook.xml",
        "workbook",
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    ),
    ".pptx": (
        "ppt/presentation.xml",
        "presentation",
        "http://schemas.openxmlformats.org/presentationml/2006/main",
        b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    ),
}
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx"}
_HEIF_BRANDS = {b"mif1", b"msf1"}


class EvidenceFileInvalid(ValueError):
    """Raised when an evidence file is unsupported or does not match its contents."""


class EvidenceFileTooLarge(ValueError):
    """Raised when an evidence file exceeds the configured per-file limit."""


class EvidenceStorageError(RuntimeError):
    """Raised when private storage is unavailable or inconsistent."""


def safe_display_filename(filename: str) -> str:
    """Return a display-only basename without path separators or control characters."""
    basename = PureWindowsPath(PurePosixPath(filename).name).name
    normalized = unicodedata.normalize("NFC", basename)
    safe_name = "".join(character for character in normalized if character.isprintable()).strip()
    if not safe_name or safe_name in {".", ".."} or len(safe_name) > 255:
        raise EvidenceFileInvalid("Evidence filename is invalid")
    return safe_name


def _reject_symlink_path_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise EvidenceStorageError("Evidence storage path cannot contain symbolic links")


def _validate_ooxml(extension: str, content: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > _MAX_OOXML_ENTRIES:
                return False
            if sum(member.file_size for member in members) > _MAX_OOXML_UNCOMPRESSED_BYTES:
                return False
            member_names = [member.filename for member in members]
            if len(member_names) != len(set(member_names)):
                return False
            for member in members:
                normalized_name = member.filename.replace("\\", "/")
                if (
                    normalized_name.startswith("/")
                    or ".." in normalized_name.split("/")
                    or stat.S_ISLNK(member.external_attr >> 16)
                    or member.flag_bits & 1
                    or (
                        member.file_size > 0
                        and (
                            member.compress_size == 0
                            or member.file_size / member.compress_size
                            > _MAX_OOXML_COMPRESSION_RATIO
                        )
                    )
                ):
                    return False
                lower_name = normalized_name.lower()
                if (
                    "vbaproject" in lower_name
                    or "/embeddings/" in f"/{lower_name}"
                    or "/activex/" in f"/{lower_name}"
                ):
                    return False
            if archive.testzip() is not None:
                return False
            part_name, root_name, root_namespace, expected_content_type = _OOXML_PARTS[extension]
            if "[Content_Types].xml" not in member_names or part_name not in member_names:
                return False
            content_type_xml = ElementTree.fromstring(archive.read("[Content_Types].xml"))
            content_types = ElementTree.tostring(content_type_xml).lower()
            if b"macroenabled" in content_types or b"activex" in content_types:
                return False
            expected_part = f"/{part_name}"
            expected_overrides = [
                element
                for element in content_type_xml
                if element.tag.endswith("}Override")
                and element.attrib.get("PartName") == expected_part
                and element.attrib.get("ContentType", "").encode().lower() == expected_content_type
            ]
            if len(expected_overrides) != 1:
                return False
            main_part = ElementTree.fromstring(archive.read(part_name))
            if main_part.tag != f"{{{root_namespace}}}{root_name}":
                return False
    except (
        OSError,
        RuntimeError,
        EOFError,
        ZlibError,
        zipfile.BadZipFile,
        KeyError,
        ElementTree.ParseError,
        ZeroDivisionError,
    ):
        return False
    return True


def _valid_heif_file(extension: str, content: bytes) -> bool:
    if len(content) < 16 or content[4:8] != b"ftyp":
        return False
    box_size = int.from_bytes(content[:4], "big")
    box_header_size = 8
    if box_size == 1:
        if len(content) < 24:
            return False
        box_size = int.from_bytes(content[8:16], "big")
        box_header_size = 16
    if (
        box_size < box_header_size + 8
        or box_size > len(content)
        or (box_size - box_header_size - 8) % 4 != 0
    ):
        return False

    major_brand_offset = box_header_size
    brands = {
        content[major_brand_offset : major_brand_offset + 4],
        *(content[offset : offset + 4] for offset in range(major_brand_offset + 8, box_size, 4)),
    }
    expected_brands = _HEIC_BRANDS if extension == ".heic" else _HEIF_BRANDS
    return bool(brands & expected_brands)


def detect_evidence_file_type(filename: str, content: bytes) -> str:
    """Validate an allowlisted format from both its suffix and file signature/content."""
    if not content:
        raise EvidenceFileInvalid("Evidence file cannot be empty")
    if len(content) > MAX_EVIDENCE_FILE_BYTES:
        raise EvidenceFileTooLarge("Evidence file exceeds the 10 MiB limit")

    safe_name = safe_display_filename(filename)
    extension = Path(safe_name).suffix.lower()
    content_type = _FILE_TYPES.get(extension)
    if content_type is None:
        raise EvidenceFileInvalid("Evidence file type is not allowed")

    if extension == ".pdf":
        valid = content.startswith(b"%PDF-") and content.rstrip().endswith(b"%%EOF")
    elif extension in {".jpg", ".jpeg"}:
        valid = content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")
    elif extension == ".png":
        valid = _valid_png(content)
    elif extension in {".heic", ".heif"}:
        valid = _valid_heif_file(extension, content)
    elif extension in _OOXML_PARTS:
        valid = _validate_ooxml(extension, content)
    else:
        try:
            text_content = content.decode("utf-8-sig")
            valid = not any(
                (ord(character) < 32 and character not in "\t\n\r") or ord(character) == 127
                for character in text_content
            )
            if valid and extension == ".csv":
                list(csv.reader(StringIO(text_content, newline=""), strict=True))
        except csv.Error:
            valid = False
        except UnicodeDecodeError:
            valid = False

    if not valid:
        raise EvidenceFileInvalid("Evidence content does not match its allowed file type")
    return content_type


def _valid_png(content: bytes) -> bool:
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    chunk_number = 0
    saw_end = False
    while offset + 12 <= len(content):
        chunk_length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(content):
            return False
        chunk_type = content[offset + 4 : offset + 8]
        chunk_data = content[offset + 8 : offset + 8 + chunk_length]
        expected_crc = int.from_bytes(content[offset + 8 + chunk_length : chunk_end], "big")
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            return False
        if chunk_number == 0 and (chunk_type != b"IHDR" or chunk_length != 13):
            return False
        chunk_number += 1
        offset = chunk_end
        if chunk_type == b"IEND":
            saw_end = chunk_length == 0 and offset == len(content)
            break
    return chunk_number >= 2 and saw_end


def store_evidence_file(storage_root: Path, content: bytes) -> tuple[str, str]:
    """Write bytes to a random private key and return the key and SHA-256 digest."""
    if len(content) > MAX_EVIDENCE_FILE_BYTES:
        raise EvidenceFileTooLarge("Evidence file exceeds the 10 MiB limit")

    temporary_path: Path | None = None
    stored_path: Path | None = None
    stored_link_created = False
    try:
        if not storage_root.is_absolute():
            raise EvidenceStorageError("Evidence storage root must be an absolute path")
        _reject_symlink_path_components(storage_root)
        storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = storage_root.resolve(strict=True)
        if not root.is_dir():
            raise EvidenceStorageError("Evidence storage root is not a directory")
        root.chmod(0o700)

        storage_key = uuid.uuid4().hex
        temporary_path = root / f".{storage_key}.tmp"
        stored_path = root / storage_key
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(temporary_path, file_flags, 0o600)
        with os.fdopen(file_descriptor, "wb") as file_handle:
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.link(temporary_path, stored_path)
        stored_link_created = True
        temporary_path.unlink()
        if os.name != "nt":
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_descriptor = os.open(root, directory_flags)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
                if stored_link_created and stored_path is not None:
                    stored_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise EvidenceStorageError(
                    "Unable to clean up incomplete private evidence file"
                ) from cleanup_error
        raise EvidenceStorageError("Unable to write private evidence file") from error

    return storage_key, hashlib.sha256(content).hexdigest()


def remove_evidence_file(storage_root: Path, storage_key: str) -> None:
    """Remove a newly written file when its database metadata transaction fails."""
    if not _STORAGE_KEY_PATTERN.fullmatch(storage_key):
        raise EvidenceStorageError("Evidence storage key is invalid")
    try:
        if not storage_root.is_absolute():
            raise EvidenceStorageError("Evidence storage root must be an absolute path")
        _reject_symlink_path_components(storage_root)
        root = storage_root.resolve(strict=True)
        path = root / storage_key
        if path.is_symlink() or path.parent != root:
            raise EvidenceStorageError("Evidence storage path is invalid")
        path.unlink(missing_ok=True)
    except OSError as error:
        raise EvidenceStorageError("Unable to remove uncommitted evidence file") from error


def evidence_file_path(storage_root: Path, storage_key: str) -> Path:
    """Resolve an opaque storage key to a regular file within the private root."""
    if not _STORAGE_KEY_PATTERN.fullmatch(storage_key):
        raise EvidenceStorageError("Evidence storage key is invalid")
    try:
        if not storage_root.is_absolute():
            raise EvidenceStorageError("Evidence storage root must be an absolute path")
        _reject_symlink_path_components(storage_root)
        root = storage_root.resolve(strict=True)
        candidate = root / storage_key
        if candidate.is_symlink():
            raise EvidenceStorageError("Evidence storage file cannot be a symbolic link")
        path = candidate.resolve(strict=True)
        if path.parent != root or not path.is_file():
            raise EvidenceStorageError("Evidence storage file is unavailable")
        return path
    except OSError as error:
        raise EvidenceStorageError("Evidence storage file is unavailable") from error
