"""Add a small, idempotent set of synthetic Rapim records to a local dev database."""

from __future__ import annotations

import re
from datetime import date, time
from typing import NotRequired, TypedDict

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.action_item import ActionItemStatus
from app.models.auth import User
from app.models.meeting import (
    Agenda,
    Meeting,
    MeetingStatus,
    MinutesDecision,
    MinutesDiscussion,
    MinutesReviewResult,
)
from app.models.organization import OrganizationUnit
from app.schemas.action_items import ActionItemCreate, ActionItemStatusChange
from app.schemas.meetings import (
    AgendaCreate,
    DecisionBriefDecisionCreate,
    DecisionBriefVersionCreate,
    MeetingCreate,
    MinutesDecisionCreate,
    MinutesDiscussionCreate,
    MinutesReviewCreate,
    MinutesRevisionCreate,
)
from app.services.action_items import change_action_item_status, create_action_item
from app.services.meetings import (
    create_agenda,
    create_decision_brief_version,
    create_meeting,
    create_minutes_revision,
    get_meeting,
    record_minutes_review,
    transition_meeting,
)

_LOCAL_DATABASE_NAME = re.compile(r"(?:^|[_-])(?:dev|development)$", re.IGNORECASE)
_LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}


class DemoDecisionPlan(TypedDict):
    text: str
    brief: str
    pic: str
    output: str
    target_date: date | None
    target_text: NotRequired[str]
    task: str
    priority: str
    action: bool


class DemoAgendaPlan(TypedDict):
    title: str
    description: str
    decisions: list[DemoDecisionPlan]


class DemoMeetingPlan(TypedDict):
    number: str
    title: str
    meeting_date: date
    location: str
    agendas: list[DemoAgendaPlan]


class DemoSeedTargetError(ValueError):
    """Raised when demo data would be written outside the explicitly local database."""


def validate_demo_seed_target(app_env: str | None, database_url: str | None) -> URL:
    """Require a local PostgreSQL database whose name clearly marks it as development."""
    if (app_env or "").strip().casefold() != "development":
        raise DemoSeedTargetError("APP_ENV must be development")
    if not database_url:
        raise DemoSeedTargetError("DATABASE_URL must be configured")
    try:
        target = make_url(database_url)
    except Exception as error:
        raise DemoSeedTargetError("DATABASE_URL is invalid") from error
    if not target.drivername.startswith("postgresql"):
        raise DemoSeedTargetError("Demo records require PostgreSQL")
    if (target.host or "").casefold() not in _LOCAL_DATABASE_HOSTS:
        raise DemoSeedTargetError("Demo records may only be added to a local database")
    if not target.database or not _LOCAL_DATABASE_NAME.search(target.database):
        raise DemoSeedTargetError("Database name must end with dev or development")
    return target


def _operator(session: Session) -> User:
    candidates = session.scalars(
        select(User).where(User.is_active.is_(True)).options(selectinload(User.roles))
    ).all()
    actor = next(
        (
            user
            for role_code in ("SEKRETARIAT", "MANAGER_LEGAL")
            for user in candidates
            if role_code in {role.role_code for role in user.roles}
        ),
        None,
    )
    if actor is None:
        raise RuntimeError("An active Secretariat or Manager Legal account is required")
    return actor


def _sample_plans() -> list[DemoMeetingPlan]:
    return [
        {
            "number": "DEMO-RAPIM-2026-11-01",
            "title": "Monitoring Program Prioritas Semester Genap",
            "meeting_date": date(2026, 11, 18),
            "location": "Ruang Rektor",
            "agendas": [
                {
                    "title": "Evaluasi target kinerja dan realisasi RKA",
                    "description": (
                        "Mencocokkan capaian indikator program prioritas dengan realisasi anggaran "
                        "dan kendala setiap unit."
                    ),
                    "decisions": [
                        {
                            "text": (
                                "Setiap unit menyelaraskan indikator program prioritas dengan RKA "
                                "dan menyampaikan capaian serta kendala kepada Sekretariat."
                            ),
                            "brief": (
                                "Konsolidasikan capaian indikator program prioritas dengan RKA "
                                "per unit."
                            ),
                            "pic": "Wakil Rektor II",
                            "output": "Rekap capaian indikator dan realisasi RKA per unit",
                            "target_date": date(2026, 12, 2),
                            "task": "Konsolidasi capaian program dan realisasi RKA",
                            "priority": "Tinggi",
                            "action": True,
                        },
                        {
                            "text": (
                                "Sekretariat menyusun laporan konsolidasi untuk menjadi bahan "
                                "monitoring pada rapat pimpinan berikutnya."
                            ),
                            "brief": (
                                "Siapkan laporan konsolidasi untuk agenda monitoring berikutnya."
                            ),
                            "pic": "Direktur Sekretariat",
                            "output": "Laporan konsolidasi program prioritas",
                            "target_date": date(2026, 12, 5),
                            "task": "Penyusunan laporan konsolidasi program prioritas",
                            "priority": "Tinggi",
                            "action": True,
                        },
                    ],
                },
                {
                    "title": "Validasi status mahasiswa nonaktif",
                    "description": (
                        "Meninjau data akademik mahasiswa nonaktif dan menentukan kebutuhan "
                        "pendampingan setiap program studi."
                    ),
                    "decisions": [
                        {
                            "text": (
                                "Program studi memverifikasi status mahasiswa nonaktif satu per "
                                "satu dan mencatat penyebab serta kebutuhan pendampingannya."
                            ),
                            "brief": (
                                "Validasi status dan kebutuhan pendampingan mahasiswa nonaktif "
                                "per program studi."
                            ),
                            "pic": "Wakil Rektor I",
                            "output": "Daftar validasi status dan rencana pendampingan",
                            "target_date": date(2026, 12, 9),
                            "task": "Validasi status mahasiswa nonaktif per program studi",
                            "priority": "Tinggi",
                            "action": True,
                        }
                    ],
                },
                {
                    "title": "Audit pemanfaatan ruang dan benturan jadwal",
                    "description": (
                        "Memeriksa kesesuaian penggunaan ruang kelas dengan jadwal perkuliahan "
                        "dan kegiatan institusi."
                    ),
                    "decisions": [
                        {
                            "text": (
                                "Lakukan audit penggunaan ruang selama satu minggu penuh dan susun "
                                "jadwal pemakaian yang mudah dilihat oleh unit terkait."
                            ),
                            "brief": (
                                "Audit utilisasi ruang selama satu minggu dan siapkan jadwal yang "
                                "mudah diakses."
                            ),
                            "pic": "Direktur Sekretariat",
                            "output": "Rekap utilisasi ruang dan jadwal penggunaan",
                            "target_date": date(2026, 12, 4),
                            "task": "Audit utilisasi ruang dan validasi benturan jadwal",
                            "priority": "Sedang",
                            "action": True,
                        }
                    ],
                },
            ],
        },
        {
            "number": "DEMO-RAPIM-2026-11-02",
            "title": "Koordinasi Kemitraan dan Komunikasi Internal",
            "meeting_date": date(2026, 11, 21),
            "location": "Ruang Rapat Rektorat",
            "agendas": [
                {
                    "title": "Penguatan kemitraan dan tindak lanjut kerja sama",
                    "description": (
                        "Meninjau kerja sama berjalan dan memilih kolaborasi yang paling "
                        "mendukung sasaran institusi."
                    ),
                    "decisions": [
                        {
                            "text": (
                                "Direktorat terkait menyusun daftar kerja sama prioritas beserta "
                                "jadwal tindak lanjut, unit pendukung, dan keluaran yang "
                                "ditargetkan."
                            ),
                            "brief": (
                                "Tetapkan daftar kerja sama prioritas, penanggung jawab unit, "
                                "dan jadwal tindak lanjut."
                            ),
                            "pic": "Wakil Rektor IV",
                            "output": "Daftar kerja sama prioritas dan rencana tindak lanjut",
                            "target_date": date(2026, 12, 10),
                            "task": "Penyusunan rencana tindak lanjut kerja sama prioritas",
                            "priority": "Tinggi",
                            "action": True,
                        }
                    ],
                },
                {
                    "title": "Format Coffee Morning dan komunikasi internal",
                    "description": (
                        "Membahas tujuan, jadwal, dan format forum komunikasi rutin antara "
                        "pimpinan dan pegawai."
                    ),
                    "decisions": [
                        {
                            "text": (
                                "Coffee Morning diselenggarakan setiap bulan dengan format "
                                "diskusi dua arah dan jadwal tahunan yang diumumkan kepada pegawai."
                            ),
                            "brief": (
                                "Tetapkan jadwal bulanan dan format diskusi dua arah untuk "
                                "Coffee Morning."
                            ),
                            "pic": "Direktur Sekretariat",
                            "output": "Kalender kegiatan dan panduan format forum",
                            "target_date": date(2026, 12, 12),
                            "task": "Penyusunan kalender Coffee Morning tahunan",
                            "priority": "Sedang",
                            "action": True,
                        }
                    ],
                },
                {
                    "title": "Penguatan kebijakan Kawasan Tanpa Rokok",
                    "description": (
                        "Meninjau cakupan kebijakan, sosialisasi, pengawasan, dan penanganan "
                        "pelanggaran di lingkungan kampus."
                    ),
                    "decisions": [
                        {
                            "text": (
                                "Kebijakan Kawasan Tanpa Rokok ditinjau kembali agar sosialisasi, "
                                "pengawasan, dan konsekuensi pelanggaran diterapkan secara "
                                "konsisten."
                            ),
                            "brief": (
                                "Selaraskan cakupan kebijakan Kawasan Tanpa Rokok dan rencana "
                                "sosialisasinya."
                            ),
                            "pic": "Wakil Rektor II",
                            "output": "Naskah tinjauan kebijakan dan rencana sosialisasi",
                            "target_date": None,
                            "target_text": "Dibahas kembali pada Rapim Desember 2026",
                            "task": "Tinjauan kebijakan Kawasan Tanpa Rokok",
                            "priority": "Sedang",
                            "action": True,
                        }
                    ],
                },
            ],
        },
    ]


def _seed_meeting(session: Session, actor: User, plan: DemoMeetingPlan) -> int:
    responsible_unit = session.scalar(
        select(OrganizationUnit).where(OrganizationUnit.unit_code == "DEMO-SYNTHETIC")
    )
    if responsible_unit is None:
        responsible_unit = OrganizationUnit(
            unit_code="DEMO-SYNTHETIC",
            name="Unit Demo Sintetis",
        )
        session.add(responsible_unit)
        session.flush()
    meeting_number = plan["number"]
    existing = session.scalar(select(Meeting.id).where(Meeting.meeting_number == meeting_number))
    if existing is not None:
        return 0

    meeting = create_meeting(
        session,
        actor,
        MeetingCreate(
            meeting_number=meeting_number,
            title=plan["title"],
            meeting_date=plan["meeting_date"],
            start_time=time(9),
            end_time=time(10, 30),
            location=plan["location"],
        ),
    )
    discussion_inputs: list[MinutesDiscussionCreate] = []
    flat_decisions: list[DemoDecisionPlan] = []
    for agenda_plan in plan["agendas"]:
        agenda = create_agenda(
            session,
            meeting.id,
            actor,
            AgendaCreate(
                expected_version=meeting.version,
                title=agenda_plan["title"],
                agenda_description=agenda_plan["description"],
            ),
            correlation_id=None,
        )
        current_meeting = get_meeting(session, meeting.id)
        assert current_meeting is not None
        meeting = current_meeting
        minute_decisions = []
        for decision in agenda_plan["decisions"]:
            target_date = decision.get("target_date")
            target_text = decision.get("target_text")
            minute_decisions.append(
                MinutesDecisionCreate(
                    decision_text=decision["text"],
                    pic_suggestion=decision["pic"],
                    output_expected=decision["output"],
                    target_date=target_date,
                    target_text=target_text,
                    is_action_item=decision["action"],
                )
            )
            flat_decisions.append(decision)
        discussion_inputs.append(
            MinutesDiscussionCreate(
                agenda_id=agenda.id,
                subject=str(agenda_plan["title"]),
                content=str(agenda_plan["description"]),
                decisions=minute_decisions,
            )
        )

    transition_meeting(session, meeting.id, actor, MeetingStatus.LIVE)
    revision = create_minutes_revision(
        session,
        meeting.id,
        actor,
        MinutesRevisionCreate(
            format_version=2,
            content=None,
            base_revision_id=None,
            discussions=discussion_inputs,
        ),
    )
    record_minutes_review(
        session,
        meeting.id,
        actor,
        MinutesReviewCreate(
            minutes_revision_id=revision.id,
            result=MinutesReviewResult.VALID,
            review_note=(
                "Data sintetis untuk demonstrasi; perlu ditinjau sebelum digunakan sebagai "
                "catatan resmi."
            ),
        ),
    )
    transition_meeting(session, meeting.id, actor, MeetingStatus.FINAL)

    source_decisions = list(
        session.scalars(
            select(MinutesDecision)
            .join(
                MinutesDiscussion,
                MinutesDiscussion.id == MinutesDecision.discussion_id,
            )
            .join(Agenda, Agenda.id == MinutesDiscussion.agenda_id)
            .where(MinutesDecision.minutes_revision_id == revision.id)
            .order_by(
                Agenda.sort_order,
                MinutesDiscussion.discussion_number,
                MinutesDecision.decision_number,
            )
        )
    )
    brief_entries = [
        DecisionBriefDecisionCreate(
            decision_id=source_decision.id,
            brief_text=str(plan_item["brief"]),
            priority=str(plan_item["priority"]),
        )
        for source_decision, plan_item in zip(source_decisions, flat_decisions, strict=True)
    ]
    create_decision_brief_version(
        session,
        meeting.id,
        actor,
        DecisionBriefVersionCreate(
            source_minutes_revision_id=revision.id,
            summary=f"{meeting_number} · {plan['title']}",
            decisions=brief_entries,
        ),
    )

    action_count = 0
    for source_decision, plan_item in zip(source_decisions, flat_decisions, strict=True):
        if not plan_item["action"]:
            continue
        task = create_action_item(
            session,
            actor,
            ActionItemCreate(
                meeting_id=meeting.id,
                source_minutes_revision_id=revision.id,
                source_decision_id=source_decision.id,
                responsible_unit_id=responsible_unit.id,
                title=str(plan_item["task"]),
                description=str(plan_item["text"]),
                output_expected=str(plan_item["output"]),
                due_date=plan_item.get("target_date"),  # type: ignore[arg-type]
                priority=str(plan_item["priority"]),
                main_pic_display_name=str(plan_item["pic"]),
            ),
        )
        if action_count == 0:
            change_action_item_status(
                session,
                actor,
                task.id,
                ActionItemStatusChange(
                    expected_version=task.version,
                    to_status=ActionItemStatus.BERPROSES,
                    note="Progres awal sintetis untuk demonstrasi.",
                ),
            )
        action_count += 1
    return action_count


def seed_demo_rapims() -> tuple[int, int]:
    settings = get_settings()
    target = validate_demo_seed_target(settings.app_env, settings.database_url)
    engine = create_engine(target, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            actor = _operator(session)
            meetings_added = 0
            tasks_added = 0
            for plan in _sample_plans():
                count = _seed_meeting(session, actor, plan)
                if count > 0:
                    meetings_added += 1
                    tasks_added += count
                else:
                    print(f"Lewati rapat demo yang sudah ada: {plan['number']}")
            return meetings_added, tasks_added
    finally:
        engine.dispose()


if __name__ == "__main__":
    meetings_added, tasks_added = seed_demo_rapims()
    print(f"Ditambahkan rapat sintetis: {meetings_added}; tindak lanjut aktif: {tasks_added}.")
