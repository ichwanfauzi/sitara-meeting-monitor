import hashlib
import struct
import zlib
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from app.services.action_item_evidence_storage import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceStorageError,
    detect_evidence_file_type,
    evidence_file_path,
    remove_evidence_file,
    safe_display_filename,
    store_evidence_file,
)


def _ooxml_file(part_name: str, content_type: str) -> bytes:
    roots = {
        "word/document.xml": (
            "document",
            "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        ),
        "xl/workbook.xml": (
            "workbook",
            "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        ),
        "ppt/presentation.xml": (
            "presentation",
            "http://schemas.openxmlformats.org/presentationml/2006/main",
        ),
    }
    root_name, namespace = roots.get(part_name, ("document", ""))
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'<Override PartName="/{part_name}" ContentType="{content_type}"/>'
            "</Types>",
        )
        archive.writestr(part_name, f'<{root_name} xmlns="{namespace}"/>')
    return buffer.getvalue()


def _valid_png() -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    header_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        body = chunk_type + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        signature
        + chunk(b"IHDR", header_data)
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _valid_heif(major_brand: bytes, compatible_brand: bytes) -> bytes:
    return struct.pack(">I4s4sI4s", 20, b"ftyp", major_brand, 0, compatible_brand)


@pytest.mark.parametrize(
    ("filename", "content", "expected_type"),
    [
        ("minutes.pdf", b"%PDF-1.7\nbody\n%%EOF", "application/pdf"),
        ("photo.jpg", b"\xff\xd8\xffsynthetic\xff\xd9", "image/jpeg"),
        ("photo.png", _valid_png(), "image/png"),
        ("photo.heic", _valid_heif(b"heic", b"heix"), "image/heic"),
        ("photo.heif", _valid_heif(b"mif1", b"msf1"), "image/heif"),
        ("notes.txt", b"synthetic notes\n", "text/plain"),
        ("table.csv", b"name,value\nsynthetic,1\n", "text/csv"),
        (
            "report.docx",
            _ooxml_file(
                "word/document.xml",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            ),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "report.xlsx",
            _ooxml_file(
                "xl/workbook.xml",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
            ),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "report.pptx",
            _ooxml_file(
                "ppt/presentation.xml",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
            ),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
def test_detects_allowlisted_evidence_from_content(
    filename: str, content: bytes, expected_type: str
) -> None:
    assert detect_evidence_file_type(filename, content) == expected_type


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("payload.exe", b"MZ synthetic"),
        ("spoof.pdf", b"not a PDF"),
        ("truncated.pdf", b"%PDF-1.7 without EOF marker"),
        ("wrong.heic", _valid_heif(b"mif1", b"msf1")),
        ("truncated.jpg", b"\xff\xd8\xffnot complete"),
        ("bad.png", b"\x89PNG\r\n\x1a\ntruncated"),
        (
            "macro.xlsm",
            _ooxml_file(
                "xl/vbaProject.bin",
                "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
            ),
        ),
        ("invalid.txt", b"\x00\x01not text"),
        ("broken.csv", b'name,"unfinished\n'),
        (
            "malformed.docx",
            _ooxml_file("word/document.xml", "wrong.content.type"),
        ),
    ],
)
def test_rejects_unsupported_or_mismatched_evidence(filename: str, content: bytes) -> None:
    with pytest.raises(ValueError):
        detect_evidence_file_type(filename, content)


def test_rejects_file_above_ten_mib() -> None:
    with pytest.raises(ValueError):
        detect_evidence_file_type(
            "large.pdf",
            b"%PDF-" + b"x" * (MAX_EVIDENCE_FILE_BYTES - 4),
        )


def test_display_filename_never_contains_client_path_or_control_characters() -> None:
    assert safe_display_filename(r"..\private\proof.pdf") == "proof.pdf"
    assert safe_display_filename("proof\r\n.pdf") == "proof.pdf"


def test_private_storage_uses_opaque_key_and_supports_cleanup(tmp_path) -> None:
    content = b"%PDF-1.7 synthetic"
    storage_key, digest = store_evidence_file(tmp_path / "private", content)

    stored_path = evidence_file_path(tmp_path / "private", storage_key)
    assert len(storage_key) == 32
    assert stored_path.name == storage_key
    assert stored_path.read_bytes() == content
    assert digest == hashlib.sha256(content).hexdigest()

    remove_evidence_file(tmp_path / "private", storage_key)
    assert not stored_path.exists()


def test_cleanup_refuses_symlinked_storage_root(tmp_path) -> None:
    storage_root = tmp_path / "private"
    storage_root.mkdir()
    storage_key = "a" * 32
    stored_path = storage_root / storage_key
    stored_path.write_bytes(b"synthetic evidence")
    symlinked_root = tmp_path / "private-link"
    try:
        symlinked_root.symlink_to(storage_root, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable in this environment: {error}")

    with pytest.raises(EvidenceStorageError, match="symbolic links"):
        remove_evidence_file(symlinked_root, storage_key)

    assert stored_path.read_bytes() == b"synthetic evidence"


def test_failed_private_file_creation_leaves_no_partial_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import action_item_evidence_storage as storage

    def fail_open(*args, **kwargs):
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(storage.os, "open", fail_open)
    with pytest.raises(storage.EvidenceStorageError):
        storage.store_evidence_file(tmp_path / "private", b"%PDF-1.7\n%%EOF")

    assert list((tmp_path / "private").iterdir()) == []
