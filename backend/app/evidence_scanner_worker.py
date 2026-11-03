"""Asynchronous ClamAV scanner worker for quarantined action-item evidence.

The durable queue is the append-only PENDING scan event in PostgreSQL. Run one
worker replica; scanner/database outages leave items PENDING for a later retry.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import time
from io import BytesIO
from pathlib import Path
from uuid import UUID

import clamd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.action_item import (
    ActionItemEvidence,
    ActionItemEvidenceKind,
    ActionItemEvidenceScan,
    ActionItemEvidenceScanStatus,
)
from app.services.action_item_evidence_storage import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceFileTooLarge,
    EvidenceStorageError,
    evidence_file_path,
)
from app.services.action_items import record_evidence_scan_result

LOGGER = logging.getLogger("sitara.evidence_scanner")


def _read_bounded_evidence_file(path: Path) -> bytes:
    """Read one unchanged regular evidence file, bounded by the upload limit."""
    try:
        file_descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise EvidenceStorageError("Evidence storage file is unavailable") from error

    try:
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceStorageError("Evidence storage file is not a regular file")
        if before.st_size > MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceFileTooLarge("Evidence file exceeds the configured size limit")

        content = bytearray()
        while len(content) <= MAX_EVIDENCE_FILE_BYTES:
            chunk = os.read(file_descriptor, MAX_EVIDENCE_FILE_BYTES + 1 - len(content))
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceFileTooLarge("Evidence file exceeds the configured size limit")

        after = os.fstat(file_descriptor)
        current_path = os.stat(path, follow_symlinks=False)
        before_signature = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_signature = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(current_path.st_mode)
            or (after.st_dev, after.st_ino) != (current_path.st_dev, current_path.st_ino)
            or before_signature != after_signature
            or len(content) != before.st_size
        ):
            raise EvidenceStorageError("Evidence storage file changed during read")
        if not content:
            raise EvidenceStorageError("Evidence storage file is empty")
        return bytes(content)
    except OSError as error:
        raise EvidenceStorageError("Evidence storage file is unavailable") from error
    finally:
        os.close(file_descriptor)


def _pending_evidence(session: Session) -> list[tuple[UUID, str, str]]:
    latest_event_number = (
        select(func.max(ActionItemEvidenceScan.event_number))
        .where(ActionItemEvidenceScan.evidence_id == ActionItemEvidence.id)
        .correlate(ActionItemEvidence)
        .scalar_subquery()
    )
    rows = session.execute(
        select(ActionItemEvidence.id, ActionItemEvidence.storage_key, ActionItemEvidence.sha256)
        .join(
            ActionItemEvidenceScan,
            ActionItemEvidenceScan.evidence_id == ActionItemEvidence.id,
        )
        .where(
            ActionItemEvidence.evidence_kind == ActionItemEvidenceKind.FILE,
            ActionItemEvidenceScan.scan_status == ActionItemEvidenceScanStatus.PENDING,
            ActionItemEvidenceScan.event_number == latest_event_number,
        )
        .order_by(ActionItemEvidence.created_at)
        .limit(25)
    ).all()
    return [(row.id, row.storage_key, row.sha256) for row in rows]


def scan_one(
    session: Session,
    scanner: clamd.ClamdNetworkSocket,
    evidence_id: UUID,
    storage_key: str,
    expected_sha256: str,
) -> bool:
    """Scan one pending file. Return True only when a terminal result was recorded."""
    settings = get_settings()
    storage_root = settings.action_item_evidence_storage_path
    if storage_root is None:
        raise RuntimeError("ACTION_ITEM_EVIDENCE_STORAGE_PATH is not configured")
    path = evidence_file_path(Path(storage_root), storage_key)
    content = _read_bounded_evidence_file(path)
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        # Fail closed: do not certify a changed file. Keep it quarantined and retry/log.
        LOGGER.error("Evidence checksum mismatch; evidence_id=%s", evidence_id)
        return False

    result = scanner.instream(BytesIO(content))
    stream_result = result.get("stream")
    if not stream_result or stream_result[0] not in {"OK", "FOUND"}:
        raise RuntimeError("ClamAV returned an unrecognized scan result")
    clean = stream_result[0] == "OK"
    version = scanner.version()
    record_evidence_scan_result(
        session,
        evidence_id,
        clean=clean,
        scanner_name="ClamAV",
        scanner_version=version[:100],
        scanned_sha256=digest,
    )
    LOGGER.info(
        "Evidence scan completed; evidence_id=%s result=%s",
        evidence_id,
        "CLEAN" if clean else "REJECTED",
    )
    return True


def run_worker() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the evidence scanner")
    if settings.action_item_evidence_storage_path is None:
        raise RuntimeError("ACTION_ITEM_EVIDENCE_STORAGE_PATH is required for the evidence scanner")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    scanner = clamd.ClamdNetworkSocket(
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout=settings.clamav_timeout_seconds,
    )
    LOGGER.info("SITARA evidence scanner worker started")
    try:
        while True:
            try:
                scanner.ping()
                with session_factory() as session:
                    pending = _pending_evidence(session)
                if not pending:
                    time.sleep(settings.evidence_scan_poll_seconds)
                    continue
                for evidence_id, storage_key, digest in pending:
                    try:
                        with session_factory() as session:
                            scan_one(session, scanner, evidence_id, storage_key, digest)
                    except Exception:
                        # Fail closed; no CLEAN result is written. The PENDING event is durable.
                        LOGGER.exception(
                            "Evidence scan failed; evidence_id=%s remains quarantined",
                            evidence_id,
                        )
                # Rate-limit repeated failures (e.g. a missing or checksum-mismatched file).
                time.sleep(settings.evidence_scan_poll_seconds)
            except Exception:
                LOGGER.exception("Scanner loop failed; retrying after delay")
                time.sleep(settings.evidence_scan_poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=get_settings().log_level.upper())
    run_worker()
