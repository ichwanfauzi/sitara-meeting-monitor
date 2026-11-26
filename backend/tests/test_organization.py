from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.db.base import Base
from app.models.auth import Role, User
from app.models.meeting import Meeting
from app.models.organization import OrganizationUnit, ReportingLine, UserUnitMembership
from app.services.organization import (
    can_access_task_scope,
    can_assign_pic,
    has_active_unit_membership,
    is_active_action_manager,
    is_active_secretariat,
    is_in_reporting_scope,
)
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


@pytest.fixture
def organization_context() -> Iterator[
    tuple[Session, dict[str, User], dict[str, OrganizationUnit]]
]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)

    roles = {
        code: Role(role_code=code, role_name=code.replace("_", " ").title())
        for code in {
            "SEKRETARIAT",
            "MANAGER_LEGAL",
            "REKTOR",
            "WAREK",
            "PIC",
            "SUPER_ADMIN",
            "PEGAWAI",
        }
    }
    session.add_all(roles.values())
    users: dict[str, User] = {}
    for key, role_codes in {
        "secretariat": ["SEKRETARIAT"],
        "manager_legal": ["MANAGER_LEGAL"],
        "mixed_manager_pic": ["MANAGER_LEGAL", "PIC"],
        "mixed_secretariat_admin": ["SEKRETARIAT", "SUPER_ADMIN"],
        "rector": ["REKTOR"],
        "warek": ["WAREK"],
        "other_rector": ["REKTOR"],
        "pic_main": ["PIC"],
        "pic_support": ["PIC"],
        "pic_unassigned": ["PIC"],
        "pic_no_membership": ["PIC"],
        "pic_expired_membership": ["PIC"],
        "pic_inactive": ["PIC"],
        "mixed_rector_pic": ["REKTOR", "PIC"],
        "ordinary": ["PEGAWAI"],
    }.items():
        user = User(
            email=f"{key}@example.test",
            full_name=key.replace("_", " ").title(),
            password_hash="synthetic-test-hash",
            is_active=key != "pic_inactive",
        )
        user.roles.extend(roles[code] for code in role_codes)
        users[key] = user
    session.add_all(users.values())

    units = {
        "university": OrganizationUnit(unit_code="UNI", name="Universitas", is_active=True),
        "faculty": OrganizationUnit(unit_code="FAC", name="Fakultas", is_active=True),
        "inactive": OrganizationUnit(unit_code="OLD", name="Unit nonaktif", is_active=False),
    }
    units["faculty"].parent = units["university"]
    session.add_all(units.values())
    session.flush()

    def add_membership(
        user: User,
        unit: OrganizationUnit = units["faculty"],
        *,
        start: datetime = NOW - timedelta(days=30),
        end: datetime | None = None,
    ) -> None:
        session.add(
            UserUnitMembership(
                user=user,
                unit=unit,
                valid_from=start,
                valid_until=end,
            )
        )

    for key in (
        "secretariat",
        "manager_legal",
        "mixed_manager_pic",
        "rector",
        "warek",
        "pic_support",
        "mixed_rector_pic",
    ):
        add_membership(users[key])
    add_membership(users["pic_main"], end=NOW + timedelta(days=30))
    add_membership(users["pic_unassigned"])
    add_membership(users["pic_inactive"])
    add_membership(users["pic_expired_membership"], end=NOW)
    add_membership(
        users["ordinary"],
        start=NOW + timedelta(days=1),
    )
    add_membership(users["other_rector"])
    add_membership(users["ordinary"], unit=units["inactive"])
    session.flush()

    for manager, subordinate in (
        ("rector", "pic_main"),
        ("warek", "pic_support"),
        ("mixed_rector_pic", "pic_main"),
        ("pic_main", "pic_support"),
        ("other_rector", "pic_main"),
    ):
        session.add(
            ReportingLine(
                manager=users[manager],
                subordinate=users[subordinate],
                valid_from=NOW - timedelta(days=10),
                valid_until=NOW if manager == "other_rector" else None,
            )
        )

    session.commit()
    assert Meeting.__tablename__ == "meetings"
    try:
        yield session, users, units
    finally:
        session.close()
        engine.dispose()


def test_active_unit_membership_respects_user_unit_and_effective_dates(
    organization_context: tuple[Session, dict[str, User], dict[str, OrganizationUnit]],
) -> None:
    session, users, units = organization_context

    assert has_active_unit_membership(session, users["pic_main"].id, at=NOW)
    assert has_active_unit_membership(session, users["pic_main"].id, units["faculty"].id, at=NOW)
    assert not has_active_unit_membership(
        session, users["pic_main"].id, units["university"].id, at=NOW
    )
    assert not has_active_unit_membership(session, users["ordinary"].id, at=NOW)
    assert not has_active_unit_membership(
        session, users["ordinary"].id, units["inactive"].id, at=NOW
    )
    assert has_active_unit_membership(session, users["other_rector"].id, at=NOW)
    assert not has_active_unit_membership(session, users["pic_expired_membership"].id, at=NOW)
    assert not has_active_unit_membership(session, users["pic_no_membership"].id, at=NOW)
    assert not has_active_unit_membership(
        session, users["pic_main"].id, at=NOW + timedelta(days=40)
    )


def test_reporting_scope_requires_active_members_and_current_reporting_path(
    organization_context: tuple[Session, dict[str, User], dict[str, OrganizationUnit]],
) -> None:
    session, users, _ = organization_context

    assert is_in_reporting_scope(session, users["rector"].id, users["pic_support"].id, at=NOW)
    assert has_active_unit_membership(session, users["other_rector"].id, at=NOW)
    assert has_active_unit_membership(session, users["pic_main"].id, at=NOW)
    assert is_in_reporting_scope(
        session,
        users["other_rector"].id,
        users["pic_main"].id,
        at=NOW - timedelta(microseconds=1),
    )
    assert not is_in_reporting_scope(
        session, users["other_rector"].id, users["pic_main"].id, at=NOW
    )
    session.add(
        ReportingLine(
            manager=users["pic_support"],
            subordinate=users["rector"],
            valid_from=NOW - timedelta(days=1),
        )
    )
    session.flush()
    assert not is_in_reporting_scope(session, users["rector"].id, users["pic_main"].id, at=NOW)
    assert not is_in_reporting_scope(
        session, users["rector"].id, users["pic_unassigned"].id, at=NOW
    )
    assert not is_in_reporting_scope(
        session, users["rector"].id, users["pic_main"].id, at=NOW + timedelta(days=40)
    )


def test_task_scope_is_role_and_organization_scoped(
    organization_context: tuple[Session, dict[str, User], dict[str, OrganizationUnit]],
) -> None:
    session, users, _ = organization_context
    assignees = {users["pic_main"].id, users["pic_support"].id}

    assert can_access_task_scope(
        session,
        users["secretariat"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=assignees - {users["pic_main"].id},
        at=NOW,
    )
    assert can_access_task_scope(
        session,
        users["manager_legal"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert can_access_task_scope(
        session,
        users["mixed_manager_pic"],
        main_pic_user_id=users["mixed_manager_pic"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["mixed_manager_pic"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["mixed_secretariat_admin"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert can_access_task_scope(
        session,
        users["rector"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["other_rector"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert can_access_task_scope(
        session,
        users["pic_support"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids={users["pic_support"].id},
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["pic_unassigned"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["mixed_rector_pic"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert can_access_task_scope(
        session,
        users["mixed_rector_pic"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids={users["mixed_rector_pic"].id},
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["ordinary"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["pic_inactive"],
        main_pic_user_id=users["pic_inactive"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )


def test_task_operators_and_meeting_leaders_can_assign_from_the_core_roster(
    organization_context: tuple[Session, dict[str, User], dict[str, OrganizationUnit]],
) -> None:
    session, users, units = organization_context
    session.add(
        UserUnitMembership(
            user_id=users["pic_unassigned"].id,
            unit_id=units["university"].id,
            valid_from=NOW - timedelta(days=1),
        )
    )
    session.commit()

    assert is_active_secretariat(session, users["secretariat"])
    assert not is_active_secretariat(session, users["mixed_secretariat_admin"])
    assert is_active_action_manager(session, users["secretariat"])
    assert is_active_action_manager(session, users["manager_legal"])
    assert not is_active_action_manager(session, users["mixed_manager_pic"])
    assert can_assign_pic(session, users["secretariat"], users["manager_legal"].id, at=NOW)
    assert can_assign_pic(session, users["manager_legal"], users["warek"].id, at=NOW)
    assert not can_assign_pic(session, users["mixed_manager_pic"], users["warek"].id, at=NOW)
    assert not can_assign_pic(session, users["rector"], users["warek"].id, at=NOW)
    assert not can_assign_pic(session, users["warek"], users["rector"].id, at=NOW)
    assert not can_assign_pic(session, users["secretariat"], users["pic_main"].id, at=NOW)
    assert not is_in_reporting_scope(session, users["warek"].id, users["pic_unassigned"].id, at=NOW)
    assert not can_assign_pic(session, users["warek"], users["pic_unassigned"].id, at=NOW)
    assert can_assign_pic(session, users["secretariat"], users["mixed_rector_pic"].id, at=NOW)
    assert not can_assign_pic(session, users["mixed_rector_pic"], users["pic_main"].id, at=NOW)
    assert not can_assign_pic(session, users["secretariat"], users["ordinary"].id, at=NOW)
    assert not can_assign_pic(session, users["secretariat"], UUID(int=0), at=NOW)
    assert not can_assign_pic(session, users["secretariat"], users["pic_inactive"].id, at=NOW)
    assert not can_assign_pic(session, users["secretariat"], users["pic_no_membership"].id, at=NOW)


def test_manager_legal_matches_secretariat_task_scope_and_assignment_authority(
    organization_context: tuple[Session, dict[str, User], dict[str, OrganizationUnit]],
) -> None:
    session, users, _ = organization_context

    assert is_active_action_manager(session, users["manager_legal"])
    assert can_access_task_scope(
        session,
        users["manager_legal"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert can_assign_pic(session, users["manager_legal"], users["warek"].id, at=NOW)
    assert not is_active_action_manager(session, users["mixed_manager_pic"])
    assert can_access_task_scope(
        session,
        users["mixed_manager_pic"],
        main_pic_user_id=users["mixed_manager_pic"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert not can_access_task_scope(
        session,
        users["mixed_manager_pic"],
        main_pic_user_id=users["pic_main"].id,
        supporting_pic_user_ids=set(),
        at=NOW,
    )
    assert not can_assign_pic(session, users["mixed_manager_pic"], users["warek"].id, at=NOW)
