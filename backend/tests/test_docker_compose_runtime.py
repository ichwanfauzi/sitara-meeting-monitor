from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_ENV_KEYS = {
    "ACTION_ITEM_EVIDENCE_STORAGE_PATH",
    "APP_ENV",
    "CLAMAV_HOST",
    "CLAMAV_PORT",
    "CLAMAV_TIMEOUT_SECONDS",
    "DATABASE_URL",
    "DATABASE_URL_CONTAINER",
    "EVIDENCE_SCAN_POLL_SECONDS",
    "LOG_LEVEL",
    "LOGIN_RATE_LIMIT_HMAC_KEY",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "POSTGRES_USER",
}


@pytest.fixture(scope="module")
def compose_config() -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose v2 is required to validate the runtime configuration")

    command = [
        "docker",
        "compose",
        "--project-directory",
        str(_REPOSITORY_ROOT),
        "--file",
        str(_REPOSITORY_ROOT / "docker-compose.yml"),
        "--env-file",
        str(_REPOSITORY_ROOT / ".env.example"),
        "--project-name",
        "sitara-config-test",
        "config",
        "--format",
        "json",
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in _COMPOSE_ENV_KEYS and not key.upper().startswith("COMPOSE_")
    }
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if result.returncode:
        pytest.fail(
            "docker compose config returned a non-zero exit code; command output suppressed"
        )
    return json.loads(result.stdout)


def test_compose_defines_integrated_runtime_services(
    compose_config: dict[str, Any],
) -> None:
    services = compose_config["services"]

    assert {"postgres", "api", "clamav", "evidence-scanner"} <= services.keys()


def test_postgres_host_port_and_data_volume_are_preserved(
    compose_config: dict[str, Any],
) -> None:
    postgres = compose_config["services"]["postgres"]

    assert any(port["published"] == "5432" and port["target"] == 5432 for port in postgres["ports"])
    assert any(
        volume["source"] == "sitara_postgres_data"
        and volume["target"] == "/var/lib/postgresql/data"
        for volume in postgres["volumes"]
    )


def test_clamav_is_internal_and_scanner_waits_for_healthy_dependencies(
    compose_config: dict[str, Any],
) -> None:
    services = compose_config["services"]
    clamav = services["clamav"]
    scanner = services["evidence-scanner"]

    assert not clamav.get("ports")
    assert "3310" in clamav["expose"]
    assert clamav["environment"]["CLAMAV_PORT"] == scanner["environment"]["CLAMAV_PORT"]
    assert "/usr/local/bin/clamav-healthcheck" in clamav["healthcheck"]["test"]
    assert clamav["healthcheck"]["start_period"] == "4m0s"
    assert clamav["user"] == "clamav"
    assert scanner["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert scanner["depends_on"]["clamav"]["condition"] == "service_healthy"
    assert scanner["command"] == ["python", "-m", "app.evidence_scanner_worker"]
    assert scanner["deploy"]["replicas"] == 1
    assert scanner["environment"]["CLAMAV_HOST"] == "clamav"
    assert scanner["environment"]["CLAMAV_PORT"] == "3310"
    assert scanner["environment"]["CLAMAV_TIMEOUT_SECONDS"] == "30"
    assert scanner["environment"]["EVIDENCE_SCAN_POLL_SECONDS"] == "5"


def test_default_clamav_port_is_shared_by_daemon_worker_and_healthcheck(
    compose_config: dict[str, Any],
) -> None:
    services = compose_config["services"]
    clamav = services["clamav"]
    scanner = services["evidence-scanner"]
    daemon_config = (_REPOSITORY_ROOT / "backend" / "clamav" / "clamd.conf").read_text()
    healthcheck = (_REPOSITORY_ROOT / "backend" / "clamav" / "healthcheck.sh").read_text()
    entrypoint = (_REPOSITORY_ROOT / "backend" / "clamav" / "entrypoint.sh").read_text()

    assert clamav["environment"]["CLAMAV_PORT"] == "3310"
    assert clamav["environment"]["CLAMAV_PORT"] == scanner["environment"]["CLAMAV_PORT"]
    assert clamav["build"]["args"]["CLAMAV_PORT"] == "3310"
    assert "TCPSocket @CLAMAV_PORT@" in daemon_config
    assert "CLAMAV_PORT" in entrypoint
    assert "s/@CLAMAV_PORT@/$CLAMAV_PORT/g" in entrypoint
    assert clamav["healthcheck"]["test"] == ["CMD", "/usr/local/bin/clamav-healthcheck"]
    assert "/dev/tcp/127.0.0.1/$CLAMAV_PORT" in healthcheck


@pytest.mark.parametrize("port", ["", "0", "65536", "not-a-port"])
def test_clamav_entrypoint_rejects_invalid_port_explicitly(port: str) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to exercise the ClamAV entrypoint validation")

    entrypoint = _REPOSITORY_ROOT / "backend" / "clamav" / "entrypoint.sh"
    result = subprocess.run(
        [bash, str(entrypoint)],
        check=False,
        capture_output=True,
        env={"CLAMAV_PORT": port, "PATH": os.environ.get("PATH", "")},
        text=True,
    )

    assert result.returncode != 0
    assert "CLAMAV_PORT must be an integer between 1 and 65535" in result.stderr


def test_custom_clamav_port_is_rendered_into_main_compose() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose v2 is required to validate the runtime configuration")

    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in _COMPOSE_ENV_KEYS and not key.upper().startswith("COMPOSE_")
    }
    environment["CLAMAV_PORT"] = "3311"
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(_REPOSITORY_ROOT),
        "--file",
        str(_REPOSITORY_ROOT / "docker-compose.yml"),
        "--env-file",
        str(_REPOSITORY_ROOT / ".env.example"),
        "--project-name",
        "sitara-config-custom-port-test",
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if result.returncode:
        pytest.fail("docker compose custom-port config failed; command output suppressed")

    services = json.loads(result.stdout)["services"]
    assert services["clamav"]["environment"]["CLAMAV_PORT"] == "3311"
    assert services["clamav"]["build"]["args"]["CLAMAV_PORT"] == "3311"
    assert "3311" in services["clamav"]["expose"]
    assert services["evidence-scanner"]["environment"]["CLAMAV_PORT"] == "3311"
    assert (
        services["clamav"]["environment"]["CLAMAV_PORT"]
        == services["evidence-scanner"]["environment"]["CLAMAV_PORT"]
    )


def test_clamav_image_uses_a_pinned_fixed_ubuntu_package_set(
    compose_config: dict[str, Any],
) -> None:
    clamav = compose_config["services"]["clamav"]
    dockerfile = (_REPOSITORY_ROOT / "backend" / "Dockerfile.clamav").read_text()

    assert clamav["image"] == "sitara-clamav:1.5.4-ubuntu24.04"
    assert clamav["build"]["dockerfile"] == "Dockerfile.clamav"
    assert (
        "ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:"
        "fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852"
    ) in dockerfile
    assert "20261030T000000Z" in dockerfile
    assert "ARG CLAMAV_VERSION=1.5.4+dfsg-0ubuntu0.24.04.1" in dockerfile
    assert "ARG LIBXML2_VERSION=2.9.14+dfsg-1.3ubuntu3.10" in dockerfile
    assert '"clamav=${CLAMAV_VERSION}"' in dockerfile
    assert '"clamdscan=${CLAMAV_VERSION}"' in dockerfile
    assert "USER clamav:clamav" in dockerfile


def test_clamav_uses_tcp_daemon_and_freshclam_reload_configuration() -> None:
    clamav_dir = _REPOSITORY_ROOT / "backend" / "clamav"
    daemon_config = (clamav_dir / "clamd.conf").read_text()
    freshclam_config = (clamav_dir / "freshclam.conf").read_text()

    assert "TCPSocket @CLAMAV_PORT@" in daemon_config
    assert "TCPAddr 0.0.0.0" in daemon_config
    assert "NotifyClamd /run/clamav/clamd.conf" in freshclam_config
    assert "Checks 24" in freshclam_config


def test_http_e2e_runner_scopes_cleanup_to_owned_resources() -> None:
    runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-http-uvicorn-e2e.ps1"
    ).read_text()

    assert '[guid]::NewGuid().ToString("N")' in runner
    assert "function Assert-OwnedComposeProject" in runner
    assert "function Assert-OwnedEvidenceVolume" in runner
    assert "function Assert-OwnedTestNetwork" in runner
    assert "function Assert-OwnedTestRunner" in runner
    assert "sitara.test.project" in runner
    assert '"down", "-v"' not in runner
    assert "docker volume rm" not in runner
    assert "docker network rm" not in runner
    assert "Assert-OwnedComposeProject -ProjectName $composeProject" in runner
    assert (
        "Assert-OwnedEvidenceVolume -VolumeName $evidenceVolumeName -ProjectName $composeProject"
        in runner
    )
    assert "-NetworkName $networkResource.Name" in runner
    assert (
        "@{ Name = $scannerNetworkName; Created = $scannerNetworkCreated; Internal = $true }"
        in runner
    )
    assert (
        "Assert-OwnedTestRunner -ContainerId $runnerContainerId -ProjectName $composeProject"
        in runner
    )
    assert "if ($usedByContainers.Count -gt 0)" in runner


def test_both_e2e_runners_share_the_validated_daemon_port() -> None:
    daemon_runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-daemon-e2e.ps1"
    ).read_text()
    http_runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-http-uvicorn-e2e.ps1"
    ).read_text()
    e2e_compose = (_REPOSITORY_ROOT / "docker-compose.e2e.yml").read_text()

    assert '$clamavPort = "3310"' in daemon_runner
    assert daemon_runner.count('"CLAMAV_PORT=$clamavPort"') >= 2
    assert "/usr/local/bin/clamav-healthcheck" in daemon_runner
    assert '$clamavPort = "3310"' in http_runner
    assert "$env:SITARA_CLAMAV_HTTP_E2E_CLAMAV_PORT = $clamavPort" in http_runner
    assert '"CLAMAV_PORT=$clamavPort"' in http_runner
    assert "CLAMAV_PORT: ${SITARA_CLAMAV_HTTP_E2E_CLAMAV_PORT:?required}" in e2e_compose


def test_api_and_scanner_share_private_evidence_volume_with_scanner_read_only(
    compose_config: dict[str, Any],
) -> None:
    services = compose_config["services"]
    api = services["api"]
    scanner = services["evidence-scanner"]
    api_volume = next(
        volume for volume in api["volumes"] if volume["target"] == "/var/lib/sitara/evidence"
    )
    scanner_volume = next(
        volume for volume in scanner["volumes"] if volume["target"] == "/var/lib/sitara/evidence"
    )

    assert api_volume["source"] == scanner_volume["source"]
    assert api_volume.get("read_only", False) is False
    assert scanner_volume["read_only"] is True
    assert (
        api["environment"]["ACTION_ITEM_EVIDENCE_STORAGE_PATH"]
        == scanner["environment"]["ACTION_ITEM_EVIDENCE_STORAGE_PATH"]
    )


def test_api_and_scanner_use_same_internal_database_without_auto_migration(
    compose_config: dict[str, Any],
) -> None:
    services = compose_config["services"]
    api = services["api"]
    scanner = services["evidence-scanner"]
    database_url = api["environment"]["DATABASE_URL"]

    assert database_url == scanner["environment"]["DATABASE_URL"]
    assert "@postgres:5432/" in database_url
    assert api["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert api.get("command") is None
    assert 'CMD ["uvicorn"' in (_REPOSITORY_ROOT / "backend" / "Dockerfile").read_text()
    assert api["ports"][0]["host_ip"] == "127.0.0.1"


def test_main_compose_networks_follow_service_least_privilege(
    compose_config: dict[str, Any],
) -> None:
    services = compose_config["services"]
    networks = compose_config["networks"]

    assert "default" not in networks
    assert set(services["api"]["networks"]) == {"api-db"}
    assert set(services["postgres"]["networks"]) == {"api-db", "scanner-db"}
    assert set(services["evidence-scanner"]["networks"]) == {"scanner-db", "scanner"}
    assert set(services["clamav"]["networks"]) == {"scanner", "clamav-egress"}
    assert networks["api-db"]["internal"] is True
    assert networks["scanner-db"]["internal"] is True
    assert networks["scanner"]["internal"] is True
    assert networks["clamav-egress"].get("internal", False) is False
    assert not services["clamav"].get("ports")
    assert services["api"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["evidence-scanner"]["depends_on"]["clamav"]["condition"] == "service_healthy"


def test_backend_image_uses_alpine_base_and_retains_non_root_runtime() -> None:
    dockerfile = (_REPOSITORY_ROOT / "backend" / "Dockerfile").read_text()

    assert "FROM python:3.12-alpine3.24" in dockerfile
    assert "addgroup -g 10001 sitara" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'CMD ["uvicorn"' in dockerfile


@pytest.fixture(scope="module")
def e2e_compose_config() -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose v2 is required to validate the E2E configuration")

    suffix = "precommit-config-test"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in _COMPOSE_ENV_KEYS and not key.upper().startswith("COMPOSE_")
    }
    environment.update(
        {
            "SITARA_CLAMAV_HTTP_E2E_DB_PASSWORD": "synthetic-password",
            "SITARA_CLAMAV_HTTP_E2E_DATABASE_URL": (
                "postgresql+psycopg://sitara_e2e:synthetic-password@"
                "sitara-clamav-e2e-postgres:5432/sitara_clamav_e2e"
            ),
            "SITARA_CLAMAV_HTTP_E2E_LIMITER_KEY": "synthetic-limiter-key",
            "SITARA_CLAMAV_HTTP_E2E_NETWORK": suffix,
            "SITARA_CLAMAV_HTTP_E2E_WORKER_DB_NETWORK": f"{suffix}-worker-db",
            "SITARA_CLAMAV_HTTP_E2E_MIGRATION_DB_NETWORK": f"{suffix}-migration-db",
            "SITARA_CLAMAV_HTTP_E2E_SCANNER_NETWORK": f"{suffix}-scanner",
            "SITARA_CLAMAV_HTTP_E2E_EGRESS_NETWORK": f"{suffix}-egress",
            "SITARA_CLAMAV_HTTP_E2E_EVIDENCE_VOLUME": f"{suffix}-evidence",
            "SITARA_CLAMAV_HTTP_E2E_PROJECT": suffix,
            "SITARA_CLAMAV_HTTP_E2E_BACKEND_IMAGE": f"sitara-backend-e2e:{suffix}",
            "SITARA_CLAMAV_HTTP_E2E_CLAMAV_IMAGE": f"sitara-clamav-e2e:{suffix}",
            "SITARA_CLAMAV_HTTP_E2E_CLAMAV_UID": "64055",
            "SITARA_CLAMAV_HTTP_E2E_CLAMAV_GID": "64055",
            "SITARA_CLAMAV_HTTP_E2E_CLAMAV_PORT": "3311",
        }
    )
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(_REPOSITORY_ROOT),
        "--file",
        str(_REPOSITORY_ROOT / "docker-compose.e2e.yml"),
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if result.returncode:
        pytest.fail("docker compose E2E config returned a non-zero exit code; output suppressed")
    return json.loads(result.stdout)


def test_e2e_compose_uses_owned_clamav_and_unique_images(
    e2e_compose_config: dict[str, Any],
) -> None:
    services = e2e_compose_config["services"]
    clamav = services["clamav"]

    assert clamav["image"] == "sitara-clamav-e2e:precommit-config-test"
    assert clamav["user"] == "clamav"
    assert clamav["environment"]["CLAMAV_PORT"] == "3311"
    assert (
        clamav["environment"]["CLAMAV_PORT"]
        == services["evidence-scanner"]["environment"]["CLAMAV_PORT"]
    )
    assert not clamav.get("ports")
    assert "3311" in clamav["expose"]
    assert "/usr/local/bin/clamav-healthcheck" in clamav["healthcheck"]["test"]
    assert clamav["healthcheck"]["start_period"] == "4m0s"
    assert any("/var/lib/clamav" in mount for mount in clamav["tmpfs"])
    assert any("uid=64055" in mount and "gid=64055" in mount for mount in clamav["tmpfs"])
    assert set(clamav["networks"]) == {"scanner", "egress"}

    backend_image = "sitara-backend-e2e:precommit-config-test"
    assert services["api"]["image"] == backend_image
    assert services["evidence-scanner"]["image"] == backend_image
    assert services["migration"]["image"] == backend_image
    assert "sitara-backend:local" not in {
        services[name]["image"] for name in ("api", "evidence-scanner", "migration")
    }
    assert services["evidence-scanner"]["depends_on"]["clamav"]["condition"] == ("service_healthy")

    assert set(services["api"]["networks"]) == {"api-db"}
    assert set(services["migration"]["networks"]) == {"migration-db"}
    assert set(services["evidence-scanner"]["networks"]) == {"worker-db", "scanner"}
    assert set(services["sitara-clamav-e2e-postgres"]["networks"]) == {
        "api-db",
        "worker-db",
        "migration-db",
    }

    assert e2e_compose_config["networks"]["api-db"]["external"] is True
    assert e2e_compose_config["networks"]["worker-db"]["external"] is True
    assert e2e_compose_config["networks"]["migration-db"]["external"] is True
    assert e2e_compose_config["networks"]["scanner"]["external"] is True
    assert e2e_compose_config["networks"]["egress"]["external"] is True
    assert "default" not in e2e_compose_config["networks"]
    assert "sitara-clamav-e2e-postgres" in services


def test_e2e_runners_verify_actual_container_network_attachments() -> None:
    daemon_runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-daemon-e2e.ps1"
    ).read_text()
    http_runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-http-uvicorn-e2e.ps1"
    ).read_text()

    for runner in (daemon_runner, http_runner):
        assert "function Assert-ContainerNetworks" in runner
        assert ".NetworkSettings.Networks" in runner
        assert "network attachments differ from the least-privilege expectation" in runner
    assert "-ExpectedNetworkNames @($testNetwork, $testScannerNetwork)" in daemon_runner
    assert "-ExpectedNetworkNames @($workerDbNetworkName, $scannerNetworkName)" in http_runner


def test_e2e_runners_use_rendered_clamd_config_for_daemon_commands() -> None:
    for script_name in (
        "test-clamav-daemon-e2e.ps1",
        "test-clamav-http-uvicorn-e2e.ps1",
    ):
        runner = (_REPOSITORY_ROOT / "backend" / "scripts" / script_name).read_text()

        assert runner.count('"clamdscan"') == runner.count('"--config-file=/run/clamav/clamd.conf"')


def test_http_e2e_starts_only_the_prevalidated_worker() -> None:
    runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-http-uvicorn-e2e.ps1"
    ).read_text()

    assert '"up", "--detach", "--no-deps", "--scale", "evidence-scanner=1"' in runner


@pytest.mark.parametrize(
    "script_name",
    ["test-clamav-daemon-e2e.ps1", "test-clamav-http-uvicorn-e2e.ps1"],
)
def test_clamav_e2e_scripts_do_not_target_main_clamav_or_backend_image(
    script_name: str,
) -> None:
    script = (_REPOSITORY_ROOT / "backend" / "scripts" / script_name).read_text()

    assert "sitara_merged_workspace" not in script
    assert "sitara-backend:local" not in script
    assert "clamdscan" in script
    assert "sitara-backend-e2e:" in script
    assert "sitara-clamav-e2e:" in script


def test_daemon_e2e_uses_owned_disposable_clamav_and_verified_cleanup() -> None:
    runner = (_REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-daemon-e2e.ps1").read_text()

    assert "function Assert-OwnedContainer" in runner
    assert "function Assert-OwnedNetwork" in runner
    assert "function Assert-OwnedImage" in runner
    assert '"network", "create"' in runner
    assert '"--health-cmd"' in runner
    assert '"/usr/local/bin/clamav-healthcheck"' in runner
    assert "sitara.test.project=$e2eProjectName" in runner
    assert "Assert-OwnedContainer -ContainerId $containerId" in runner
    assert "Assert-OwnedNetwork `" in runner
    assert "Assert-OwnedImage -ImageName $imageResource.Name" in runner
    assert "docker-compose.yml" not in runner
    assert "sitara-backend:local" not in runner


def test_http_e2e_preflight_mounts_both_runner_scripts_read_only() -> None:
    runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-http-uvicorn-e2e.ps1"
    ).read_text()

    assert (
        '$daemonScriptSource = (Join-Path $repoRoot "backend\\scripts\\test-clamav-daemon-e2e.ps1")'
        in runner
    )

    assert (
        '$daemonScriptMount = "type=bind,source=$daemonScriptSource,target=/workspace/repo/backend/'
        'scripts/test-clamav-daemon-e2e.ps1,readonly"'
    ) in runner
    assert '"--mount",\n        $daemonScriptMount' in runner


def test_http_e2e_detaches_clamav_egress_without_duplicate_network_connect() -> None:
    runner = (
        _REPOSITORY_ROOT / "backend" / "scripts" / "test-clamav-http-uvicorn-e2e.ps1"
    ).read_text()

    assert '"network", "disconnect", $egressNetworkName, $clamavContainerId' in runner
    assert (
        '"network", "connect", "--alias", "clamav", $networkName, $clamavContainerId' not in runner
    )
    assert (
        '$composeSource = (Join-Path $repoRoot "docker-compose.e2e.yml").Replace("\\", "/")'
        in runner
    )
    assert (
        '$composeManifestMount = "type=bind,source=$composeSource,target=/workspace/repo/'
        'docker-compose.e2e.yml,readonly"'
    ) in runner
    assert '"--mount",\n        $composeManifestMount' in runner


def test_e2e_network_ownership_guards_handle_empty_and_unverifiable_networks() -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is required to exercise the E2E ownership guards")

    regression_script = _REPOSITORY_ROOT / "backend" / "tests" / "test_e2e_network_ownership.ps1"
    command = [powershell, "-NoProfile"]
    if Path(powershell).name.lower() == "powershell.exe":
        command.extend(["-ExecutionPolicy", "Bypass"])
    command.extend(["-File", str(regression_script)])

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"PowerShell E2E network ownership regression failed:\n{result.stdout}\n{result.stderr}"
    )
