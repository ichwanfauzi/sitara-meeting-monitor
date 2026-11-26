from __future__ import annotations

import hashlib
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import clamd
import pytest
from app import evidence_scanner_worker as worker
from app.services.action_item_evidence_storage import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceFileTooLarge,
    EvidenceStorageError,
)
from sqlalchemy.orm import Session


class FakeScanner(clamd.ClamdNetworkSocket):
    def __init__(self, status: str = "OK") -> None:
        super().__init__()
        self.status = status
        self.scanned_content: bytes | None = None

    def instream(self, stream: BytesIO) -> dict[str, tuple[str, str | None]]:
        self.scanned_content = stream.read()
        assert self.scanned_content
        return {"stream": (self.status, "Eicar-Test-Signature" if self.status == "FOUND" else None)}

    def version(self) -> str:
        return "ClamAV test version"

    def ping(self) -> str:
        return "PONG"


def test_scan_one_records_clean_result_for_matching_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        Session(), FakeScanner(), evidence_id, storage_key, hashlib.sha256(content).hexdigest()
    )

    assert result is True
    assert calls[0]["clean"] is True
    assert calls[0]["scanner_name"] == "ClamAV"


def test_scan_one_scans_file_exactly_at_maximum_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"x" * MAX_EVIDENCE_FILE_BYTES
    storage_key = "9" * 32
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
    scanner = FakeScanner()

    result = worker.scan_one(
        Session(), scanner, uuid4(), storage_key, hashlib.sha256(content).hexdigest()
    )

    assert result is True
    assert scanner.scanned_content == content
    assert calls[0]["clean"] is True
    assert calls[0]["scanned_sha256"] == hashlib.sha256(content).hexdigest()


def test_scan_one_rejects_file_one_byte_over_maximum_before_scanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_key = "8" * 32
    (tmp_path / storage_key).write_bytes(b"x" * (MAX_EVIDENCE_FILE_BYTES + 1))
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
    scanner = FakeScanner()
    monkeypatch.setattr(
        worker.os,
        "read",
        lambda *args: (_ for _ in ()).throw(AssertionError("oversized file was read")),
    )

    with pytest.raises(EvidenceFileTooLarge):
        worker.scan_one(Session(), scanner, uuid4(), storage_key, "0" * 64)

    assert scanner.scanned_content is None
    assert calls == []


def test_scan_one_rejects_file_that_grows_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"synthetic evidence"
    storage_key = "7" * 32
    path = tmp_path / storage_key
    path.write_bytes(content)
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
    scanner = FakeScanner()
    original_read = worker.os.read
    grew = False

    def grow_before_read(file_descriptor: int, size: int) -> bytes:
        nonlocal grew
        if not grew:
            with path.open("ab") as evidence_file:
                evidence_file.write(b" changed")
            grew = True
        return original_read(file_descriptor, size)

    monkeypatch.setattr(worker.os, "read", grow_before_read)

    with pytest.raises(EvidenceStorageError, match="changed during read"):
        worker.scan_one(
            Session(), scanner, uuid4(), storage_key, hashlib.sha256(content).hexdigest()
        )

    assert grew is True
    assert scanner.scanned_content is None
    assert calls == []


def test_scan_one_rejects_file_that_grows_over_limit_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"initial"
    storage_key = "6" * 32
    path = tmp_path / storage_key
    path.write_bytes(content)
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
    scanner = FakeScanner()
    original_read = worker.os.read
    read_requests = []

    def grow_over_limit_before_read(file_descriptor: int, size: int) -> bytes:
        read_requests.append(size)
        with path.open("ab") as evidence_file:
            evidence_file.write(b"x" * (MAX_EVIDENCE_FILE_BYTES + 1 - len(content)))
        return original_read(file_descriptor, size)

    monkeypatch.setattr(worker.os, "read", grow_over_limit_before_read)

    with pytest.raises(EvidenceFileTooLarge):
        worker.scan_one(
            Session(), scanner, uuid4(), storage_key, hashlib.sha256(content).hexdigest()
        )

    assert read_requests == [MAX_EVIDENCE_FILE_BYTES + 1]
    assert scanner.scanned_content is None
    assert calls == []


def test_scan_one_records_rejected_result_when_clamav_finds_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        Session(),
        FakeScanner("FOUND"),
        uuid4(),
        storage_key,
        hashlib.sha256(content).hexdigest(),
    )

    assert calls[0]["clean"] is False


def test_scan_one_does_not_record_result_when_checksum_mismatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    result = worker.scan_one(Session(), FakeScanner(), uuid4(), storage_key, "0" * 64)

    assert result is False
    assert calls == []


def test_scan_one_keeps_evidence_pending_when_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    with pytest.raises(EvidenceStorageError, match="Evidence storage file is unavailable"):
        worker.scan_one(Session(), FakeScanner(), uuid4(), "e" * 32, "0" * 64)

    assert calls == []


def test_scan_one_keeps_evidence_pending_when_clamav_result_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"synthetic evidence"
    storage_key = "f" * 32
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

    with pytest.raises(RuntimeError, match="unrecognized scan result"):
        worker.scan_one(
            Session(),
            FakeScanner("UNKNOWN"),
            uuid4(),
            storage_key,
            hashlib.sha256(content).hexdigest(),
        )

    assert calls == []


@pytest.mark.parametrize(
    ("response", "error"),
    [
        pytest.param({"stream": ("UNKNOWN", None)}, RuntimeError, id="unknown-status"),
        pytest.param({}, RuntimeError, id="empty-response"),
        pytest.param({"stream": ()}, RuntimeError, id="empty-stream-result"),
        pytest.param({"stream": ([], None)}, TypeError, id="malformed-stream-status"),
        pytest.param(None, AttributeError, id="missing-response"),
    ],
)
def test_scan_one_does_not_record_invalid_clamav_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: object,
    error: type[Exception],
) -> None:
    content = b"synthetic evidence"
    storage_key = "5" * 32
    (tmp_path / storage_key).write_bytes(content)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(action_item_evidence_storage_path=tmp_path),
    )
    calls = []

    class InvalidResponseScanner(clamd.ClamdNetworkSocket):
        def instream(self, stream: BytesIO) -> object:
            assert stream.read() == content
            return response

        def version(self) -> str:
            raise AssertionError("invalid scanner response must not be accepted")

    monkeypatch.setattr(
        worker,
        "record_evidence_scan_result",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    with pytest.raises(error):
        worker.scan_one(
            Session(),
            InvalidResponseScanner(),
            uuid4(),
            storage_key,
            hashlib.sha256(content).hexdigest(),
        )

    assert calls == []


def test_scan_one_keeps_evidence_pending_when_clamav_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"synthetic evidence"
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

    class TimedOutScanner(clamd.ClamdNetworkSocket):
        def instream(self, stream: BytesIO) -> dict[str, tuple[str, str | None]]:
            assert stream.read() == content
            raise TimeoutError("synthetic ClamAV timeout")

    with pytest.raises(TimeoutError, match="synthetic ClamAV timeout"):
        worker.scan_one(
            Session(),
            TimedOutScanner(),
            uuid4(),
            storage_key,
            hashlib.sha256(content).hexdigest(),
        )

    assert calls == []


def test_worker_continues_scanning_other_evidence_after_one_file_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_id, second_id = uuid4(), uuid4()
    processed = []
    disposed = []
    daemon = FakeScanner()

    class StopWorker(BaseException):
        pass

    class FakeEngine:
        def dispose(self) -> None:
            disposed.append(True)

    def create_session_factory(**kwargs: object) -> Callable[[], Session]:
        return Session

    def scan_one(
        session: Session,
        scanner: clamd.ClamdNetworkSocket,
        evidence_id: UUID,
        storage_key: str,
        expected_sha256: str,
    ) -> bool:
        processed.append(evidence_id)
        if evidence_id == first_id:
            raise FileNotFoundError("synthetic missing evidence")
        return True

    def stop_worker(_seconds: float) -> None:
        raise StopWorker

    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+psycopg://sitara_e2e@localhost/sitara_clamav_e2e",
            action_item_evidence_storage_path=tmp_path,
            clamav_host="clamav",
            clamav_port=3310,
            clamav_timeout_seconds=1,
            evidence_scan_poll_seconds=1,
            log_level="INFO",
        ),
    )
    monkeypatch.setattr(worker, "create_engine", lambda *args, **kwargs: FakeEngine())
    monkeypatch.setattr(worker, "sessionmaker", create_session_factory)
    monkeypatch.setattr(worker.clamd, "ClamdNetworkSocket", lambda **kwargs: daemon)
    monkeypatch.setattr(
        worker,
        "_pending_evidence",
        lambda session: [(first_id, "1" * 32, "0" * 64), (second_id, "2" * 32, "1" * 64)],
    )
    monkeypatch.setattr(worker, "scan_one", scan_one)
    monkeypatch.setattr(worker.time, "sleep", stop_worker)

    with pytest.raises(StopWorker):
        worker.run_worker()

    assert processed == [first_id, second_id]
    assert disposed == [True]


def test_scan_one_keeps_evidence_pending_when_clamav_connection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    class UnavailableScanner(clamd.ClamdNetworkSocket):
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
            Session(),
            UnavailableScanner(),
            uuid4(),
            storage_key,
            hashlib.sha256(content).hexdigest(),
        )

    assert calls == []
