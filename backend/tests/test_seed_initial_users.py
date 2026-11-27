import json
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from app import seed_initial_users as seed_users
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.models.auth import Role, User
from app.models.organization import OrganizationUnit, ReportingLine, UserUnitMembership
from app.seed_initial_users import (
    ProvisioningConflict,
    SeedConfigurationError,
    main,
    provision_initial_users,
    validate_seed_target,
)
from app.services.organization import can_access_task_scope, can_assign_pic
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def seed_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    assert "meetings" in Base.metadata.tables
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add_all(
        [
            Role(role_code=code, role_name=name)
            for code, name in (
                ("REKTOR", "Rektor"),
                ("WAREK", "Wakil Rektor"),
                ("SEKRETARIAT", "Sekretariat"),
                ("MANAGER_LEGAL", "Manager Legal"),
                ("SUPER_ADMIN", "Super Admin"),
                ("PIC", "PIC"),
            )
        ]
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_seed_repository_root_matches_checkout_and_container_layouts(tmp_path: Path) -> None:
    checkout_root = tmp_path / "checkout"
    (checkout_root / ".git").mkdir(parents=True)
    checkout_module = checkout_root / "backend" / "app" / "seed_initial_users.py"
    checkout_module.parent.mkdir(parents=True)
    assert seed_users._repository_root(checkout_module) == checkout_root

    image_root = tmp_path / "container-app"
    image_root.mkdir()
    (image_root / "pyproject.toml").touch()
    image_module = image_root / "app" / "seed_initial_users.py"
    image_module.parent.mkdir()
    assert seed_users._repository_root(image_module) == image_root


def test_provision_initial_users_creates_expected_users_roles_and_secure_passwords(
    seed_session: Session, tmp_path: Path
) -> None:
    credentials_path = tmp_path / "initial-users.json"

    result = provision_initial_users(seed_session, credentials_path)

    users = list(seed_session.scalars(select(User).order_by(User.email)))
    units = list(seed_session.scalars(select(OrganizationUnit)))
    memberships = list(seed_session.scalars(select(UserUnitMembership)))
    credential_data = json.loads(credentials_path.read_text(encoding="utf-8"))
    credentials = {item["email"]: item["password"] for item in credential_data["accounts"]}

    assert len(users) == 7
    assert len({user.email for user in users}) == 7
    assert {user.email for user in users} == set(result.created_emails)
    assert {
        user.email: (user.full_name, user.job_title, {role.role_code for role in user.roles})
        for user in users
    } == {
        "iwa.garniwa@users.sitara.test": (
            "Prof. Dr. Ir. Iwa Garniwa M.K, M.T. IPU., ASEAN Eng., APEC Eng",
            "Rektor ITPLN",
            {"REKTOR"},
        ),
        "susy.rostiyanti@users.sitara.test": (
            "Prof. Dr. Susy Fatena Rostiyanti, ST., M.Sc",
            "Wakil Rektor I Bidang Akademik",
            {"WAREK"},
        ),
        "heryawan@users.sitara.test": (
            "Heryawan, S.E., S.H., M.H., M.Ak., Ak., C.A., QRGP., QIA.",
            "Wakil Rektor II Bidang Sumber Daya",
            {"WAREK"},
        ),
        "purnomo@users.sitara.test": (
            "Ir. Purnomo, ST., MT",
            "Wakil Rektor III Bidang Kemahasiswaan",
            {"WAREK"},
        ),
        "ahsin.sidqi@users.sitara.test": (
            "Dr. Ir. M. Ahsin Sidqi, M.M., IPU., ASEAN. Eng., QRGP",
            "Wakil Rektor IV Bidang Kerjasama",
            {"WAREK"},
        ),
        "heru.setiawan@users.sitara.test": (
            "Heru Setiawan, S.H., M.H.",
            "Direktur Rektorat",
            {"SEKRETARIAT"},
        ),
        "herry.zulkarnaen@users.sitara.test": (
            "Herry Zulkarnaen, SH",
            "Manager Legal",
            {"MANAGER_LEGAL"},
        ),
    }
    assert all(user.is_active for user in users)
    assert all("SUPER_ADMIN" not in {role.role_code for role in user.roles} for user in users)
    assert [(unit.unit_code, unit.name) for unit in units] == [("REKTORAT", "Rektorat ITPLN")]
    assert len(memberships) == 7
    assert all(user.password_hash not in credentials.values() for user in users)
    assert len(set(credentials.values())) == 7
    assert all(verify_password(credentials[user.email], user.password_hash) for user in users)
    assert result.created_emails == tuple(sorted(credentials))
    assert result.credentials_file == credentials_path


def test_demo_seed_adds_synthetic_pic_accounts_and_leadership_scope(
    seed_session: Session, tmp_path: Path
) -> None:
    credentials_path = tmp_path / "demo-accounts.json"

    result = provision_initial_users(
        seed_session,
        credentials_path,
        include_demo_pics=True,
    )

    users = {user.email: user for user in seed_session.scalars(select(User))}
    pic_emails = {
        "pic-a@users.sitara.test",
        "pic-b@users.sitara.test",
        "pic-c@users.sitara.test",
    }
    pic_users = {email: users[email] for email in pic_emails}
    demo_unit = seed_session.scalar(
        select(OrganizationUnit).where(OrganizationUnit.unit_code == "SITARA-DEMO")
    )
    assert demo_unit is not None
    reporting_lines = list(seed_session.scalars(select(ReportingLine)))
    demo_memberships = list(
        seed_session.scalars(
            select(UserUnitMembership).where(UserUnitMembership.unit_id == demo_unit.id)
        )
    )
    credential_data = json.loads(credentials_path.read_text(encoding="utf-8"))
    credentials = {item["email"]: item["password"] for item in credential_data["accounts"]}
    secretary = users["heru.setiawan@users.sitara.test"]

    assert len(result.created_emails) == 10
    assert len(users) == 10
    assert (demo_unit.name, demo_unit.is_active) == ("SITARA Demo (Synthetic)", True)
    assert len(list(seed_session.scalars(select(UserUnitMembership)))) == 10
    assert len(reporting_lines) == 15
    assert {membership.user_id for membership in demo_memberships} == {
        pic.id for pic in pic_users.values()
    }
    assert set(credentials) == set(users)
    assert len(set(credentials.values())) == 10
    assert all(
        {role.role_code for role in user.roles} == {"PIC"} and user.is_active
        for user in pic_users.values()
    )

    leaders = [
        user
        for user in users.values()
        if {role.role_code for role in user.roles}.intersection({"REKTOR", "WAREK"})
    ]
    assert len(leaders) == 5
    assert {(line.manager_user_id, line.subordinate_user_id) for line in reporting_lines} == {
        (leader.id, pic.id) for leader in leaders for pic in pic_users.values()
    }
    for leader in leaders:
        for pic in pic_users.values():
            assert not can_assign_pic(seed_session, leader, pic.id)
            assert can_access_task_scope(
                seed_session,
                leader,
                main_pic_user_id=pic.id,
                supporting_pic_user_ids=set(),
            )

    pic_a = pic_users["pic-a@users.sitara.test"]
    pic_b = pic_users["pic-b@users.sitara.test"]
    assert can_access_task_scope(
        seed_session,
        secretary,
        main_pic_user_id=pic_a.id,
        supporting_pic_user_ids=set(),
    )
    assert not can_access_task_scope(
        seed_session,
        pic_a,
        main_pic_user_id=pic_b.id,
        supporting_pic_user_ids=set(),
    )


def test_demo_seed_is_idempotent_without_rotating_pic_credentials(
    seed_session: Session, tmp_path: Path
) -> None:
    credentials_path = tmp_path / "demo-accounts.json"
    first = provision_initial_users(
        seed_session,
        credentials_path,
        include_demo_pics=True,
    )
    initial_bytes = credentials_path.read_bytes()
    initial_hashes = {user.email: user.password_hash for user in seed_session.scalars(select(User))}
    seed_session.rollback()

    second = provision_initial_users(
        seed_session,
        credentials_path,
        include_demo_pics=True,
    )

    assert len(first.created_emails) == 10
    assert second.created_emails == ()
    assert second.credentials_file is None
    assert len(list(seed_session.scalars(select(User)))) == 10
    assert len(list(seed_session.scalars(select(ReportingLine)))) == 15
    assert {
        user.email: user.password_hash for user in seed_session.scalars(select(User))
    } == initial_hashes
    assert credentials_path.read_bytes() == initial_bytes


def test_demo_seed_adds_pics_after_default_accounts_without_overwriting_credentials(
    seed_session: Session,
    tmp_path: Path,
) -> None:
    initial_credentials_path = tmp_path / "initial-users.json"
    demo_credentials_path = tmp_path / "demo-pic-credentials.json"
    initial = provision_initial_users(seed_session, initial_credentials_path)
    initial_hashes = {user.email: user.password_hash for user in seed_session.scalars(select(User))}
    initial_credentials = initial_credentials_path.read_bytes()
    seed_session.rollback()

    demo = provision_initial_users(
        seed_session,
        demo_credentials_path,
        include_demo_pics=True,
    )

    demo_credentials = json.loads(demo_credentials_path.read_text(encoding="utf-8"))
    current_hashes = {user.email: user.password_hash for user in seed_session.scalars(select(User))}
    assert len(initial.created_emails) == 7
    assert set(demo.created_emails) == {
        "pic-a@users.sitara.test",
        "pic-b@users.sitara.test",
        "pic-c@users.sitara.test",
    }
    assert {email: current_hashes[email] for email in initial_hashes} == initial_hashes
    assert len(demo_credentials["accounts"]) == 3
    assert initial_credentials_path.read_bytes() == initial_credentials
    assert len(list(seed_session.scalars(select(ReportingLine)))) == 15


def test_seed_is_idempotent_and_does_not_rotate_existing_passwords(
    seed_session: Session, tmp_path: Path
) -> None:
    credentials_path = tmp_path / "initial-users.json"
    first = provision_initial_users(seed_session, credentials_path)
    initial_hashes = {user.email: user.password_hash for user in seed_session.scalars(select(User))}
    initial_file = credentials_path.read_bytes()
    seed_session.rollback()

    second = provision_initial_users(seed_session, credentials_path)

    assert len(first.created_emails) == 7
    assert second.created_emails == ()
    assert second.credentials_file is None
    assert len(list(seed_session.scalars(select(User)))) == 7
    assert {
        user.email: user.password_hash for user in seed_session.scalars(select(User))
    } == initial_hashes
    assert credentials_path.read_bytes() == initial_file


def test_seed_rejects_existing_credentials_file_before_database_changes(
    seed_session: Session, tmp_path: Path
) -> None:
    credentials_path = tmp_path / "initial-users.json"
    credentials_path.write_text("existing local credentials", encoding="utf-8")

    with pytest.raises(ProvisioningConflict, match="already exists"):
        provision_initial_users(seed_session, credentials_path)

    assert list(seed_session.scalars(select(User))) == []
    assert credentials_path.read_text(encoding="utf-8") == "existing local credentials"


def test_seed_aborts_without_partial_changes_on_account_conflict(
    seed_session: Session, tmp_path: Path
) -> None:
    unit = OrganizationUnit(unit_code="REKTORAT", name="Rektorat ITPLN", is_active=True)
    role = seed_session.scalar(select(Role).where(Role.role_code == "REKTOR"))
    assert role is not None
    seed_session.add(unit)
    conflicting_user = User(
        email="iwa.garniwa@users.sitara.test",
        full_name="Unexpected existing identity",
        job_title="Unexpected title",
        password_hash=hash_password("existing-password"),
        is_active=True,
        roles=[role],
    )
    seed_session.add(conflicting_user)
    seed_session.commit()
    credentials_path = tmp_path / "initial-users.json"

    with pytest.raises(ProvisioningConflict, match="account attributes"):
        provision_initial_users(seed_session, credentials_path)

    assert list(seed_session.scalars(select(User))) == [conflicting_user]
    assert not credentials_path.exists()
    assert list(seed_session.scalars(select(OrganizationUnit))) == [unit]


@pytest.mark.parametrize("app_env", ["production", "staging", "", None])
def test_seed_target_rejects_non_development_or_unclear_environment(
    app_env: str | None,
) -> None:
    with pytest.raises(SeedConfigurationError, match="APP_ENV"):
        validate_seed_target(app_env, "postgresql+psycopg://user:pass@localhost/sitara_test")


@pytest.mark.parametrize(
    ("database_url", "error"),
    [
        (None, "SITARA_SEED_DATABASE_URL"),
        ("postgresql+psycopg://user:pass@example.com/sitara_test", "local"),
        ("postgresql+psycopg://user:pass@localhost/sitara_prod", "test or development"),
        ("postgresql+psycopg://user:pass@localhost/sitara", "test or development"),
        ("sqlite:///sitara_test.db", "PostgreSQL"),
    ],
)
def test_seed_target_rejects_unscoped_or_unsafe_database_urls(
    database_url: str | None, error: str
) -> None:
    with pytest.raises(SeedConfigurationError, match=error):
        validate_seed_target("testing", database_url)


@pytest.mark.parametrize(
    ("app_env", "database_url", "error"),
    [
        (
            "development",
            "postgresql+psycopg://user:pass@localhost/sitara_demo_test",
            "testing",
        ),
        (
            "testing",
            "postgresql+psycopg://user:pass@localhost/sitara_demo_dev",
            "test database",
        ),
    ],
)
def test_demo_seed_requires_testing_environment_and_test_database(
    app_env: str,
    database_url: str,
    error: str,
) -> None:
    with pytest.raises(SeedConfigurationError, match=error):
        validate_seed_target(app_env, database_url, include_demo_pics=True)


def test_seed_target_accepts_explicit_local_testing_database() -> None:
    validate_seed_target(
        "testing",
        "postgresql+psycopg://sitara_test:synthetic@127.0.0.1:55432/sitara_stage11o1_test",
    )


def test_seed_demo_pic_target_accepts_only_explicit_local_testing_database() -> None:
    validate_seed_target(
        "testing",
        "postgresql+psycopg://sitara_test:synthetic@127.0.0.1:55432/sitara_mvp_demo_test",
        include_demo_pics=True,
    )


def test_seed_accepts_database_at_current_migration_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, _statement: object) -> "FakeConnection":
            return self

        def one(self) -> tuple[str, str]:
            return ("sitara_dev", "0031_super_admin_account_management")

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

        def dispose(self) -> None:
            pass

    monkeypatch.setattr(seed_users, "create_engine", lambda *_args, **_kwargs: FakeEngine())
    target = make_url("postgresql+psycopg://user:pass@localhost/sitara_dev")

    seed_users._verify_database_identity(
        "postgresql+psycopg://user:pass@localhost/sitara_dev", target
    )


def test_seed_cli_blocks_demo_pics_outside_testing_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "SITARA_SEED_DATABASE_URL",
        "postgresql+psycopg://user:pass@localhost/sitara_demo_test",
    )
    monkeypatch.setattr(sys, "argv", ["seed_initial_users", "--include-demo-pics"])

    assert main() == 1
    assert "APP_ENV=testing" in capsys.readouterr().err


def test_seed_target_accepts_explicit_local_development_database() -> None:
    validate_seed_target(
        "development",
        "postgresql+psycopg://sitara_app:synthetic@localhost/sitara_dev",
    )


def test_seed_requires_all_canonical_roles_to_exist(seed_session: Session, tmp_path: Path) -> None:
    warek = seed_session.scalar(select(Role).where(Role.role_code == "WAREK"))
    assert warek is not None
    seed_session.delete(warek)
    seed_session.commit()

    with pytest.raises(ProvisioningConflict, match="Required role"):
        provision_initial_users(seed_session, tmp_path / "initial-users.json")

    assert list(seed_session.scalars(select(User))) == []
    assert seed_session.scalar(select(OrganizationUnit)) is None
