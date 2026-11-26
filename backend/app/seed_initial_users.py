"""Provision the initial SITARA accounts in an explicitly scoped local database."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.roles import MEETING_LEADER_ROLES
from app.core.security import hash_password
from app.models import meeting as meeting_models
from app.models.auth import Role, User
from app.models.organization import OrganizationUnit, ReportingLine, UserUnitMembership

LATEST_MIGRATION = "0028_meeting_external_attendees"
UNIT_CODE = "REKTORAT"
UNIT_NAME = "Rektorat ITPLN"
DEMO_UNIT_CODE = "SITARA-DEMO"
DEMO_UNIT_NAME = "SITARA Demo (Synthetic)"
LOCAL_DATABASE_SUFFIX = re.compile(r"(?:^|[_-])(?:dev|development|test|testing)$")
TEST_DATABASE_SUFFIX = re.compile(r"(?:^|[_-])(?:test|testing)$")


def _repository_root(module_file: Path) -> Path:
    resolved_module = module_file.resolve()
    for parent in resolved_module.parents:
        if (parent / ".git").exists() or (parent / "PROJECT_CONTEXT.md").is_file():
            return parent
    for parent in resolved_module.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "app").is_dir():
            return parent
    return resolved_module.parent.parent


REPOSITORY_ROOT = _repository_root(Path(__file__))


class SeedConfigurationError(ValueError):
    """Raised when seed execution is not explicitly scoped to a safe environment."""


class ProvisioningConflict(ValueError):
    """Raised when existing account data conflicts with the initial seed definition."""


@dataclass(frozen=True)
class InitialAccount:
    email: str
    full_name: str
    job_title: str
    role_code: str
    unit_code: str = UNIT_CODE


@dataclass(frozen=True)
class ProvisioningResult:
    accounts: tuple[InitialAccount, ...]
    credentials_file: Path | None

    @property
    def created_emails(self) -> tuple[str, ...]:
        return tuple(sorted(account.email for account in self.accounts))


INITIAL_ACCOUNTS = (
    InitialAccount(
        "iwa.garniwa@users.sitara.test",
        "Prof. Dr. Ir. Iwa Garniwa M.K, M.T. IPU., ASEAN Eng., APEC Eng",
        "Rektor ITPLN",
        "REKTOR",
    ),
    InitialAccount(
        "susy.rostiyanti@users.sitara.test",
        "Prof. Dr. Susy Fatena Rostiyanti, ST., M.Sc",
        "Wakil Rektor I Bidang Akademik",
        "WAREK",
    ),
    InitialAccount(
        "heryawan@users.sitara.test",
        "Heryawan, S.E., S.H., M.H., M.Ak., Ak., C.A., QRGP., QIA.",
        "Wakil Rektor II Bidang Sumber Daya",
        "WAREK",
    ),
    InitialAccount(
        "purnomo@users.sitara.test",
        "Ir. Purnomo, ST., MT",
        "Wakil Rektor III Bidang Kemahasiswaan",
        "WAREK",
    ),
    InitialAccount(
        "ahsin.sidqi@users.sitara.test",
        "Dr. Ir. M. Ahsin Sidqi, M.M., IPU., ASEAN. Eng., QRGP",
        "Wakil Rektor IV Bidang Kerjasama",
        "WAREK",
    ),
    InitialAccount(
        "heru.setiawan@users.sitara.test",
        "Heru Setiawan, S.H., M.H.",
        "Direktur Rektorat",
        "SEKRETARIAT",
    ),
    InitialAccount(
        "herry.zulkarnaen@users.sitara.test",
        "Herry Zulkarnaen, SH",
        "Manager Legal",
        "MANAGER_LEGAL",
    ),
)


DEMO_PIC_ACCOUNTS = (
    InitialAccount(
        "pic-a@users.sitara.test",
        "PIC A (Demo)",
        "PIC Demo A",
        "PIC",
        DEMO_UNIT_CODE,
    ),
    InitialAccount(
        "pic-b@users.sitara.test",
        "PIC B (Demo)",
        "PIC Demo B",
        "PIC",
        DEMO_UNIT_CODE,
    ),
    InitialAccount(
        "pic-c@users.sitara.test",
        "PIC C (Demo)",
        "PIC Demo C",
        "PIC",
        DEMO_UNIT_CODE,
    ),
)


def validate_seed_target(
    app_env: str | None,
    database_url: str | None,
    *,
    include_demo_pics: bool = False,
) -> URL:
    """Require an explicit local PostgreSQL URL whose database is named for test/dev."""
    normalized_env = (app_env or "").strip().casefold()
    if normalized_env not in {"development", "testing"}:
        raise SeedConfigurationError("APP_ENV must be explicitly set to development or testing")
    if include_demo_pics and normalized_env != "testing":
        raise SeedConfigurationError(
            "Demo PIC accounts may only be provisioned with APP_ENV=testing"
        )
    if not database_url:
        raise SeedConfigurationError("SITARA_SEED_DATABASE_URL must be explicitly set")
    try:
        target = make_url(database_url)
    except ArgumentError as error:
        raise SeedConfigurationError("SITARA_SEED_DATABASE_URL is invalid") from error
    if not target.drivername.startswith("postgresql"):
        raise SeedConfigurationError("SITARA_SEED_DATABASE_URL must use PostgreSQL")
    host = (target.host or "").casefold()
    is_loopback = host in {"localhost", "postgres"}
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        raise SeedConfigurationError("SITARA_SEED_DATABASE_URL must target a local database")
    database_name = (target.database or "").casefold()
    if not database_name.startswith("sitara_") or not LOCAL_DATABASE_SUFFIX.search(database_name):
        raise SeedConfigurationError(
            "SITARA_SEED_DATABASE_URL database name must be a SITARA test or development database"
        )
    if include_demo_pics and not TEST_DATABASE_SUFFIX.search(database_name):
        raise SeedConfigurationError("Demo PIC accounts require a SITARA test database")
    return target


def _default_credentials_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SITARA" / "initial-user-credentials.json"
    return Path.home() / ".sitara" / "initial-user-credentials.json"


def _validate_credentials_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == REPOSITORY_ROOT or REPOSITORY_ROOT in resolved.parents:
        raise SeedConfigurationError("Credential files must be stored outside the repository")
    return resolved


def _secure_credentials_file(path: Path) -> None:
    if os.name == "nt":
        try:
            identity = subprocess.run(
                ["whoami"], check=True, capture_output=True, text=True
            ).stdout.strip()
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(F)"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise SeedConfigurationError(
                "Could not restrict the credential file ACL to the current Windows user"
            ) from error
    else:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _write_credentials(path: Path, accounts: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    file_descriptor: int | None = None
    created = False
    try:
        file_descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        created = True
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as credential_file:
            file_descriptor = None
            json.dump({"accounts": accounts}, credential_file, ensure_ascii=False, indent=2)
            credential_file.write("\n")
        _secure_credentials_file(path)
    except BaseException:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if created:
            path.unlink(missing_ok=True)
        raise


def _validate_existing_account(
    session: Session,
    specification: InitialAccount,
    unit_id: UUID,
) -> User | None:
    user = session.scalar(
        select(User).options(selectinload(User.roles)).where(User.email == specification.email)
    )
    if user is None:
        return None
    role_codes = {role.role_code for role in user.roles}
    if (
        user.full_name != specification.full_name
        or user.job_title != specification.job_title
        or not user.is_active
        or role_codes != {specification.role_code}
    ):
        raise ProvisioningConflict(
            f"Existing account attributes conflict for {specification.email}"
        )
    now = datetime.now(UTC)
    membership = session.scalar(
        select(UserUnitMembership.id).where(
            UserUnitMembership.user_id == user.id,
            UserUnitMembership.unit_id == unit_id,
            UserUnitMembership.valid_from <= now,
            UserUnitMembership.valid_until.is_(None) | (UserUnitMembership.valid_until > now),
        )
    )
    if membership is None:
        raise ProvisioningConflict(
            f"Existing account has no current {specification.unit_code} membership: "
            f"{specification.email}"
        )
    return user


def _ensure_demo_reporting_lines(
    session: Session,
    users_by_email: dict[str, User],
) -> None:
    now = datetime.now(UTC)
    leaders = (account for account in INITIAL_ACCOUNTS if account.role_code in MEETING_LEADER_ROLES)
    for leader_specification in leaders:
        leader = users_by_email[leader_specification.email]
        for pic_specification in DEMO_PIC_ACCOUNTS:
            pic = users_by_email[pic_specification.email]
            existing_line = session.scalar(
                select(ReportingLine.id)
                .where(
                    ReportingLine.manager_user_id == leader.id,
                    ReportingLine.subordinate_user_id == pic.id,
                    ReportingLine.valid_from <= now,
                    (ReportingLine.valid_until.is_(None)) | (ReportingLine.valid_until > now),
                )
                .limit(1)
            )
            if existing_line is None:
                session.add(
                    ReportingLine(
                        manager_user_id=leader.id,
                        subordinate_user_id=pic.id,
                        valid_from=now,
                    )
                )


def provision_initial_users(
    session: Session,
    credentials_file: Path | None = None,
    *,
    include_demo_pics: bool = False,
) -> ProvisioningResult:
    """Create missing accounts once and write their generated passwords to a private file."""
    meeting_models.Meeting.__mapper__.registry.configure()
    credential_path = _validate_credentials_path(credentials_file or _default_credentials_path())
    written_credentials_file = False
    new_accounts: list[InitialAccount] = []
    specifications = INITIAL_ACCOUNTS + (DEMO_PIC_ACCOUNTS if include_demo_pics else ())
    try:
        with session.begin():
            role_codes = {account.role_code for account in specifications}
            roles = {
                role.role_code: role
                for role in session.scalars(select(Role).where(Role.role_code.in_(role_codes)))
            }
            missing_roles = role_codes - roles.keys()
            if missing_roles:
                raise ProvisioningConflict(
                    "Required role codes are missing: " + ", ".join(sorted(missing_roles))
                )

            specifications_by_unit: dict[str, list[InitialAccount]] = {}
            for specification in specifications:
                specifications_by_unit.setdefault(specification.unit_code, []).append(specification)

            units: dict[str, OrganizationUnit] = {}
            unit_names = {
                UNIT_CODE: UNIT_NAME,
                DEMO_UNIT_CODE: DEMO_UNIT_NAME,
            }
            for unit_code, unit_specifications in specifications_by_unit.items():
                unit = session.scalar(
                    select(OrganizationUnit).where(OrganizationUnit.unit_code == unit_code)
                )
                existing_users = list(
                    session.scalars(
                        select(User.email).where(
                            User.email.in_(tuple(account.email for account in unit_specifications))
                        )
                    )
                )
                unit_name = unit_names[unit_code]
                if unit is None and existing_users:
                    raise ProvisioningConflict(
                        f"Existing seeded accounts require the {unit_code} organization unit"
                    )
                if unit is not None and (unit.name != unit_name or not unit.is_active):
                    raise ProvisioningConflict(f"Existing {unit_code} organization unit conflicts")
                if unit is None:
                    unit = OrganizationUnit(
                        unit_code=unit_code,
                        name=unit_name,
                        is_active=True,
                    )
                    session.add(unit)
                    session.flush()
                units[unit_code] = unit

            users_by_email: dict[str, User] = {}
            for specification in specifications:
                existing_user = _validate_existing_account(
                    session,
                    specification,
                    units[specification.unit_code].id,
                )
                if existing_user is None:
                    new_accounts.append(specification)
                else:
                    users_by_email[specification.email] = existing_user

            generated_credentials: list[dict[str, str]] = []
            for specification in new_accounts:
                password = secrets.token_urlsafe(24)
                user = User(
                    email=specification.email,
                    full_name=specification.full_name,
                    job_title=specification.job_title,
                    password_hash=hash_password(password),
                    is_active=True,
                    roles=[roles[specification.role_code]],
                )
                session.add(user)
                session.flush()
                users_by_email[specification.email] = user
                session.add(
                    UserUnitMembership(
                        user_id=user.id,
                        unit_id=units[specification.unit_code].id,
                        valid_from=datetime.now(UTC),
                    )
                )
                generated_credentials.append(
                    {
                        "email": specification.email,
                        "full_name": specification.full_name,
                        "role": specification.role_code,
                        "password": password,
                    }
                )

            if include_demo_pics:
                _ensure_demo_reporting_lines(session, users_by_email)

            if generated_credentials:
                if credential_path.exists():
                    raise ProvisioningConflict(
                        f"Credential file already exists; refusing to overwrite: {credential_path}"
                    )
                _write_credentials(credential_path, generated_credentials)
                written_credentials_file = True
            session.flush()
    except BaseException:
        if written_credentials_file:
            credential_path.unlink(missing_ok=True)
        raise

    created = tuple(account for account in specifications if account in new_accounts)
    return ProvisioningResult(
        accounts=created,
        credentials_file=credential_path if created else None,
    )


def _verify_database_identity(database_url: str, target: URL) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            database_name, migration_head = connection.execute(
                text("SELECT current_database(), (SELECT version_num FROM alembic_version LIMIT 1)")
            ).one()
    except SQLAlchemyError as error:
        raise SeedConfigurationError(
            "Could not verify the local database identity and migration head"
        ) from error
    finally:
        engine.dispose()
    if database_name != target.database:
        raise SeedConfigurationError("Connected database does not match the requested test target")
    if migration_head != LATEST_MIGRATION:
        raise SeedConfigurationError(f"Database must already be migrated to {LATEST_MIGRATION}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help="new local credential file path (defaults outside the repository)",
    )
    parser.add_argument(
        "--include-demo-pics",
        action="store_true",
        help=("add PIC A/B/C for an isolated testing environment and _test database only"),
    )
    arguments = parser.parse_args()
    app_env = os.environ.get("APP_ENV")
    database_url = os.environ.get("SITARA_SEED_DATABASE_URL")
    try:
        target = validate_seed_target(
            app_env,
            database_url,
            include_demo_pics=arguments.include_demo_pics,
        )
        if database_url is None:
            raise SeedConfigurationError("SITARA_SEED_DATABASE_URL must be explicitly set")
        _verify_database_identity(database_url, target)
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            factory = sessionmaker(bind=engine, expire_on_commit=False)
            with factory() as session:
                result = provision_initial_users(
                    session,
                    arguments.credentials_file,
                    include_demo_pics=arguments.include_demo_pics,
                )
        finally:
            engine.dispose()
    except (ProvisioningConflict, SeedConfigurationError) as error:
        print(f"Initial user provisioning failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Initial user provisioning failed during a database operation.", file=sys.stderr)
        return 1

    if result.accounts:
        print(f"Provisioned {len(result.accounts)} initial SITARA account(s):")
        for account in result.accounts:
            print(f"- {account.email} ({account.role_code})")
        print(f"Initial passwords are stored in the restricted file: {result.credentials_file}")
    else:
        print("All initial SITARA accounts already exist; no credentials were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
