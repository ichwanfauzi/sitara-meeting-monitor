from __future__ import annotations

import pytest
from app.seed_demo_rapims import DemoSeedTargetError, validate_demo_seed_target


def test_demo_seed_accepts_only_local_development_postgres() -> None:
    target = validate_demo_seed_target(
        "development",
        "postgresql+psycopg://sitara_app:placeholder@postgres:5432/sitara_dev",
    )

    assert target.database == "sitara_dev"
    assert target.host == "postgres"


@pytest.mark.parametrize(
    ("app_env", "database_url"),
    [
        ("production", "postgresql://user:placeholder@postgres:5432/sitara_dev"),
        ("development", "postgresql://user:placeholder@example.com:5432/sitara_dev"),
        ("development", "postgresql://user:placeholder@postgres:5432/sitara"),
        ("development", "sqlite:///sitara_dev.db"),
    ],
)
def test_demo_seed_refuses_nonlocal_or_non_development_targets(
    app_env: str,
    database_url: str,
) -> None:
    with pytest.raises(DemoSeedTargetError):
        validate_demo_seed_target(app_env, database_url)
