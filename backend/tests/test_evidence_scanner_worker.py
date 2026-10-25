from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import clamd
import pytest
from app import evidence_scanner_worker as worker


class FakeScanner:
    def __init__(self, status: str = "OK") -> None:
        self.status = status

    def instream(self, stream: BytesIO) -> dict[str, tuple[str, str | None]]:
        assert stream.read()
        return {"stream": (self.status, "Eicar-Test-Signature" if self.status == "FOUND" else None)}

    def version(self) -> str:
        return "ClamAV test version"


def test_scan_one_records_clean_result_for_matching_file(tmp_path: Path, monkeypatch) -> None:
    content = b"%PDF-1.7 test"
    storage_key = "a" * 32
    (tmp_path / storage_key).write_bytes(content)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(action_item_evidence_storage_path=tmp_path),
    )
    calls = []
    monkeypatch.setattr(
        worker,
        "record_evidence_scan_result",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    evidence_id = uuid4()
    result = worker.scan_one(
        object(), FakeScanner(), evidence_id, storage_key, hashlib.sha256(content).hexdigest()
    )

    assert result is True
    assert calls[0]["clean"] is True
    assert calls[0]["scanner_name"] == "ClamAV"


def test_scan_one_records_rejected_result_when_clamav_finds_signature(
    tmp_path: Path, monkeypatch
) -> None:
    content = b"test malware signature"
    storage_key = "b" * 32
    (tmp_path / storage_key).write_bytes(content)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(action_item_evidence_storage_path=tmp_path),
    )
    calls = []

    monkeypatch.setattr(
        worker,
        "record_evidence_scan_result",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    worker.scan_one(
        object(), FakeScanner("FOUND"), uuid4(), storage_key, hashlib.sha256(content).hexdigest()
    )

    assert calls[0]["clean"] is False


def test_scan_one_does_not_record_result_when_checksum_mismatches(
    tmp_path: Path, monkeypatch
) -> None:
    storage_key = "c" * 32
    (tmp_path / storage_key).write_bytes(b"changed file")
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(action_item_evidence_storage_path=tmp_path),
    )
    calls = []

    monkeypatch.setattr(
        worker,
        "record_evidence_scan_result",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    result = worker.scan_one(object(), FakeScanner(), uuid4(), storage_key, "0" * 64)

    assert result is False
    assert calls == []


def test_scan_one_keeps_evidence_pending_when_clamav_connection_fails(
    tmp_path: Path, monkeypatch
) -> None:
    content = b"synthetic evidence"
    storage_key = "d" * 32
    (tmp_path / storage_key).write_bytes(content)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(action_item_evidence_storage_path=tmp_path),
    )
    calls = []

    class UnavailableScanner:
        def instream(self, stream: BytesIO) -> dict[str, tuple[str, str | None]]:
            assert stream.read() == content
            raise clamd.ConnectionError("synthetic scanner outage")

    monkeypatch.setattr(
        worker,
        "record_evidence_scan_result",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    with pytest.raises(clamd.ConnectionError, match="synthetic scanner outage"):
        worker.scan_one(
            object(),
            UnavailableScanner(),
            uuid4(),
            storage_key,
            hashlib.sha256(content).hexdigest(),
        )

    assert calls == []
