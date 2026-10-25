Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-DockerChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$Quiet
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& docker @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        $detail = ($output | Out-String).Trim()
        throw "docker $($Arguments[0]) failed with exit code $exitCode. $detail"
    }
    if (-not $Quiet -and $output.Count -gt 0) {
        Write-Host ($output -join [Environment]::NewLine)
    }
    return ($output -join [Environment]::NewLine)
}

function Get-ContainerStatus {
    param([Parameter(Mandatory = $true)][string]$ContainerId)

    $status = Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{.State.Status}}",
        $ContainerId
    ) -Quiet
    return $status.Trim()
}

function Test-ContainerPath {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$Path
    )

    & docker exec $ContainerId test -f $Path 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$previousLocation = Get-Location
Set-Location $repoRoot

$createdContainerIds = [System.Collections.Generic.List[string]]::new()
$cleanupErrors = [System.Collections.Generic.List[string]]::new()
$mainError = $null
$testNetwork = $null
$testNetworkCreated = $false
$workerBaseTag = "sitara-clamav-e2e-worker-base:local"
$workerBaseTagCreated = $false
$testRunnerImage = $null
$testRunnerImageCreated = $false
$clamavContainerId = $null
$clamavConnected = $false
$devWorkerId = $null
$devWorkerWasRunning = $false
$devWorkerStoppedByHarness = $false
$postgresId = $null
$daemonWorkerId = $null

$suffix = "{0}-{1}" -f [DateTime]::UtcNow.ToString("yyyyMMddHHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$networkName = "sitara-clamav-e2e-$suffix"
$postgresName = "sitara-clamav-e2e-postgres-$suffix"
$daemonWorkerName = "sitara-clamav-e2e-worker-$suffix"
$databasePassword = [guid]::NewGuid().ToString("N")
$databaseUrl = "postgresql+psycopg://sitara_e2e:$databasePassword@sitara-clamav-e2e-postgres:5432/sitara_clamav_e2e"
$limiterKey = [guid]::NewGuid().ToString("N")
$controlPath = "/tmp/sitara-clamav-e2e-control"
$evidencePath = "/var/lib/sitara/evidence"

try {
    $dockerOs = (Invoke-DockerChecked -Arguments @("info", "--format", "{{.OSType}}") -Quiet).Trim()
    if ($dockerOs -ne "linux") {
        throw "This disposable ClamAV test harness requires Linux containers"
    }

    $clamavContainerId = (Invoke-DockerChecked -Arguments @("compose", "ps", "-q", "clamav") -Quiet).Trim()
    if (-not $clamavContainerId) {
        throw "The existing Compose ClamAV service is not running; start it before this test"
    }
    $clamavState = Get-ContainerStatus -ContainerId $clamavContainerId
    $clamavHealth = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
        $clamavContainerId
    ) -Quiet).Trim()
    if ($clamavState -ne "running" -or $clamavHealth -ne "healthy") {
        throw "The existing Compose ClamAV service must be running and healthy"
    }

    $projectWorkerIds = @(
        (Invoke-DockerChecked -Arguments @("compose", "ps", "-q", "evidence-scanner") -Quiet) -split "\r?\n" |
            Where-Object { $_ }
    )
    if ($projectWorkerIds.Count -gt 1) {
        throw "More than one Compose evidence-scanner container is running; refusing daemon E2E"
    }
    if ($projectWorkerIds.Count -eq 1) {
        $devWorkerId = $projectWorkerIds[0].Trim()
        $devWorkerWasRunning = (Get-ContainerStatus -ContainerId $devWorkerId) -eq "running"
    }
    $allWorkerIds = @(
        (Invoke-DockerChecked -Arguments @(
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.service=evidence-scanner"
        ) -Quiet) -split "\r?\n" |
            Where-Object { $_ }
    )
    if ($allWorkerIds.Count -gt $projectWorkerIds.Count) {
        throw "Another evidence-scanner container is running; refusing to run a second worker"
    }

    Write-Host "Building the evidence-scanner image used by the disposable daemon test."
    $null = Invoke-DockerChecked -Arguments @("compose", "build", "evidence-scanner")
    $composeImages = Invoke-DockerChecked -Arguments @("compose", "config", "--images") -Quiet
    $workerImageReference = ($composeImages -split "\r?\n" |
        Where-Object { $_ -match "evidence-scanner" } |
        Select-Object -First 1).Trim()
    if (-not $workerImageReference) {
        throw "Could not resolve the built evidence-scanner image reference"
    }
    $workerImage = (Invoke-DockerChecked -Arguments @(
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        $workerImageReference
    ) -Quiet).Trim()
    if (-not $workerImage) {
        throw "Could not inspect the built evidence-scanner image"
    }
    $existingBaseImageId = Invoke-DockerChecked -Arguments @("image", "ls", "-q", $workerBaseTag) -Quiet
    if ($existingBaseImageId.Trim()) {
        $existingBaseImage = Invoke-DockerChecked -Arguments @(
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            $workerBaseTag
        ) -Quiet
        if ($existingBaseImage.Trim() -ne $workerImage) {
            throw "The reserved test-runner base tag points to a different image; refusing to overwrite it"
        }
    }
    else {
        $null = Invoke-DockerChecked -Arguments @("image", "tag", $workerImage, $workerBaseTag) -Quiet
        $workerBaseTagCreated = $true
    }
    $testRunnerImage = "sitara-clamav-e2e-runner:$suffix"
    $existingRunnerImage = Invoke-DockerChecked -Arguments @(
        "image",
        "ls",
        "-q",
        $testRunnerImage
    ) -Quiet
    if ($existingRunnerImage.Trim()) {
        throw "The unique disposable test-runner image tag already exists"
    }
    Write-Host "Building a disposable pytest runner image from the current worker image."
    $null = Invoke-DockerChecked -Arguments @(
        "build",
        "--build-arg",
        "SITARA_WORKER_IMAGE=$workerBaseTag",
        "--tag",
        $testRunnerImage,
        "--file",
        "backend/Dockerfile.e2e",
        "backend"
    )
    $testRunnerImageCreated = $true

    $null = Invoke-DockerChecked -Arguments @("network", "create", "--internal", $networkName) -Quiet
    $testNetworkCreated = $true
    $testNetwork = $networkName
    $null = Invoke-DockerChecked -Arguments @(
        "network",
        "connect",
        "--alias",
        "clamav",
        $testNetwork,
        $clamavContainerId
    ) -Quiet
    $clamavConnected = $true

    $postgresId = (Invoke-DockerChecked -Arguments @(
        "run",
        "--detach",
        "--rm",
        "--name",
        $postgresName,
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--network",
        $testNetwork,
        "--network-alias",
        "sitara-clamav-e2e-postgres",
        "--security-opt",
        "no-new-privileges:true",
        "--tmpfs",
        "/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=768m,mode=1777",
        "--env",
        "POSTGRES_DB=sitara_clamav_e2e",
        "--env",
        "POSTGRES_USER=sitara_e2e",
        "--env",
        "POSTGRES_PASSWORD=$databasePassword",
        "postgres:16-alpine"
    ) -Quiet).Trim()
    if (-not $postgresId) {
        throw "Could not start the disposable PostgreSQL container"
    }
    $createdContainerIds.Add($postgresId)

    $postgresReady = $false
    $postgresTimer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($postgresTimer.Elapsed.TotalSeconds -lt 45) {
        & docker exec $postgresId pg_isready -U sitara_e2e -d sitara_clamav_e2e 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $postgresReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $postgresReady) {
        throw "Disposable PostgreSQL did not become ready within 45 seconds"
    }

    $postgresMountsJson = Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .Mounts}}",
        $postgresId
    ) -Quiet
    $postgresTmpfsJson = Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.Tmpfs}}",
        $postgresId
    ) -Quiet
    $postgresTmpfs = ConvertFrom-Json -InputObject $postgresTmpfsJson
    $postgresTmpfsTargets = @($postgresTmpfs.PSObject.Properties | ForEach-Object { $_.Name })
    $postgresPortBindings = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.PortBindings}}",
        $postgresId
    ) -Quiet).Trim()
    if ($postgresMountsJson.Trim() -ne "[]" -or
        $postgresTmpfsTargets.Count -ne 1 -or
        $postgresTmpfsTargets[0] -ne "/var/lib/postgresql/data" -or
        $postgresPortBindings -notin @("{}", "null")) {
        throw "Disposable PostgreSQL must have tmpfs-only data, no persistent mounts, and no host port"
    }

    Write-Host "Running Alembic upgrade head against sitara_clamav_e2e on the isolated Docker network."
    $null = Invoke-DockerChecked -Arguments @(
        "run",
        "--rm",
        "--network",
        $testNetwork,
        "--env",
        "DATABASE_URL=$databaseUrl",
        $workerImage,
        "alembic",
        "upgrade",
        "head"
    )
    $revision = (Invoke-DockerChecked -Arguments @(
        "exec",
        $postgresId,
        "psql",
        "-U",
        "sitara_e2e",
        "-d",
        "sitara_clamav_e2e",
        "-Atc",
        "SELECT version_num FROM alembic_version"
    ) -Quiet).Trim()
    if ($revision -ne "0011_evidence_scan_quarantine") {
        throw "Disposable database migration head was '$revision', expected 0011_evidence_scan_quarantine"
    }
    Write-Host "Disposable database migration head: $revision"

    $dockerTestsSource = (Join-Path $repoRoot "backend\tests").Replace("\", "/")
    $testMount = "type=bind,source=$dockerTestsSource,target=/workspace/tests,readonly"
    $runnerLogPath = "/tmp/sitara-clamav-e2e-pytest.log"
    $runnerExitPath = "/tmp/sitara-clamav-e2e-pytest.exit"
    $runnerCommand = 'python -m pytest /workspace/tests/test_action_items.py::test_clamav_daemon_retries_pending_evidence_after_scanner_recovery -q -s -p no:cacheprovider -o addopts= > /tmp/sitara-clamav-e2e-pytest.log 2>&1; status=$?; echo "$status" > /tmp/sitara-clamav-e2e-pytest.exit; exit "$status"'
    Write-Host "Disposable PostgreSQL, evidence, and control paths will use tmpfs; only read-only test source is bind-mounted."

    if ($devWorkerWasRunning) {
        Write-Host "Temporarily stopping only this Compose project's evidence-scanner to keep one daemon active."
        $null = Invoke-DockerChecked -Arguments @("compose", "stop", "evidence-scanner")
        $devWorkerStoppedByHarness = $true
        if ((Get-ContainerStatus -ContainerId $devWorkerId) -ne "exited") {
            throw "The existing evidence-scanner did not stop before the disposable daemon started"
        }
    }

    $daemonWorkerId = (Invoke-DockerChecked -Arguments @(
        "run",
        "--detach",
        "--name",
        $daemonWorkerName,
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--network",
        $testNetwork,
        "--mount",
        $testMount,
        "--tmpfs",
        "$evidencePath`:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",
        "--tmpfs",
        "$controlPath`:rw,nosuid,nodev,noexec,size=8m,uid=10001,gid=10001,mode=0700",
        "--env",
        "DATABASE_URL=$databaseUrl",
        "--env",
        "ACTION_ITEM_EVIDENCE_STORAGE_PATH=$evidencePath",
        "--env",
        "CLAMAV_HOST=clamav",
        "--env",
        "CLAMAV_PORT=3310",
        "--env",
        "CLAMAV_TIMEOUT_SECONDS=1",
        "--env",
        "EVIDENCE_SCAN_POLL_SECONDS=1",
        "--env",
        "LOG_LEVEL=INFO",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "SITARA_CLAMAV_E2E=1",
        "--env",
        "SITARA_CLAMAV_DAEMON_E2E=1",
        "--env",
        "SITARA_CLAMAV_E2E_DATABASE_URL=$databaseUrl",
        "--env",
        "SITARA_CLAMAV_E2E_CONTROL_PATH=$controlPath",
        "--env",
        "LOGIN_RATE_LIMIT_HMAC_KEY=$limiterKey",
        $testRunnerImage,
        "python",
        "-m",
        "app.evidence_scanner_worker"
    ) -Quiet).Trim()
    if (-not $daemonWorkerId) {
        throw "Could not start the disposable evidence-scanner daemon"
    }
    $createdContainerIds.Add($daemonWorkerId)
    $null = Invoke-DockerChecked -Arguments @("network", "disconnect", $testNetwork, $clamavContainerId) -Quiet
    $clamavConnected = $false
    Write-Host "ClamAV is disconnected only from the disposable network to exercise fail-closed retry."

    $daemonMountsJson = Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .Mounts}}",
        $daemonWorkerId
    ) -Quiet
    $daemonMounts = @(ConvertFrom-Json -InputObject $daemonMountsJson)
    $daemonTmpfsJson = Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.Tmpfs}}",
        $daemonWorkerId
    ) -Quiet
    $daemonTmpfs = ConvertFrom-Json -InputObject $daemonTmpfsJson
    $daemonTmpfsTargets = @($daemonTmpfs.PSObject.Properties | ForEach-Object { $_.Name })
    $daemonPortBindings = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.PortBindings}}",
        $daemonWorkerId
    ) -Quiet).Trim()
    $daemonCommand = Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{.Path}} {{json .Args}}",
        $daemonWorkerId
    ) -Quiet
    if ($daemonMounts.Count -ne 1 -or
        $daemonMounts[0].Type -ne "bind" -or
        $daemonMounts[0].Destination -ne "/workspace/tests" -or
        $daemonMounts[0].RW -ne $false -or
        $daemonTmpfsTargets.Count -ne 2 -or
        $daemonTmpfsTargets -notcontains $evidencePath -or
        $daemonTmpfsTargets -notcontains $controlPath -or
        $daemonPortBindings -notin @("{}", "null") -or
        $daemonCommand -notmatch "app.evidence_scanner_worker") {
        throw "Daemon must run the worker module with tmpfs storage, one read-only test mount, and no host ports"
    }

    $null = Invoke-DockerChecked -Arguments @(
        "exec",
        "--detach",
        $daemonWorkerId,
        "sh",
        "-c",
        $runnerCommand
    ) -Quiet

    $outageTimer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($outageTimer.Elapsed.TotalSeconds -lt 120) {
        if (Test-ContainerPath -ContainerId $daemonWorkerId -Path "$controlPath/outage-verified") {
            break
        }
        if (Test-ContainerPath -ContainerId $daemonWorkerId -Path $runnerExitPath) {
            $runnerLogs = Invoke-DockerChecked -Arguments @("exec", $daemonWorkerId, "cat", $runnerLogPath) -Quiet
            Write-Host $runnerLogs
            throw "Disposable daemon E2E runner exited before verifying the scanner outage"
        }
        if ((Get-ContainerStatus -ContainerId $daemonWorkerId) -ne "running") {
            throw "Evidence-scanner daemon exited before the outage condition was verified"
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-ContainerPath -ContainerId $daemonWorkerId -Path "$controlPath/outage-verified")) {
        throw "Disposable daemon did not verify PENDING status during scanner outage within 120 seconds"
    }

    $outageLogs = Invoke-DockerChecked -Arguments @("logs", $daemonWorkerId) -Quiet
    if ($outageLogs -notmatch "Scanner loop failed; retrying after delay") {
        throw "Evidence-scanner did not log retry attempts while ClamAV was disconnected"
    }
    if ($outageLogs -match "Evidence scan completed") {
        throw "Evidence-scanner unexpectedly completed a scan while ClamAV was disconnected"
    }
    Write-Host "The single daemon logged scanner retries; both uploads remained PENDING without CLEAN results."
    $null = Invoke-DockerChecked -Arguments @(
        "network",
        "connect",
        "--alias",
        "clamav",
        $testNetwork,
        $clamavContainerId
    ) -Quiet
    $clamavConnected = $true
    $null = Invoke-DockerChecked -Arguments @(
        "exec",
        $daemonWorkerId,
        "sh",
        "-c",
        "touch $controlPath/recovery-ready"
    ) -Quiet
    Write-Host "ClamAV reconnected to the disposable network; the same daemon process will resume polling."

    $runnerTimer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($runnerTimer.Elapsed.TotalSeconds -lt 60) {
        if (Test-ContainerPath -ContainerId $daemonWorkerId -Path $runnerExitPath) {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-ContainerPath -ContainerId $daemonWorkerId -Path $runnerExitPath)) {
        throw "Disposable API/pytest process did not finish within 60 seconds after scanner recovery"
    }
    $runnerExitCode = (Invoke-DockerChecked -Arguments @(
        "exec",
        $daemonWorkerId,
        "cat",
        $runnerExitPath
    ) -Quiet).Trim()
    $runnerLogs = Invoke-DockerChecked -Arguments @("exec", $daemonWorkerId, "cat", $runnerLogPath) -Quiet
    Write-Host $runnerLogs
    if ($runnerExitCode -ne "0") {
        throw "Disposable daemon E2E pytest exited with code $runnerExitCode"
    }

    $statusSql = @"
SELECT e.original_filename || '|' || s.scan_status || '|' || (s.scanned_sha256 = e.sha256)::text
FROM action_item_evidence AS e
JOIN LATERAL (
    SELECT scan_status, scanned_sha256
    FROM action_item_evidence_scans
    WHERE evidence_id = e.id
    ORDER BY event_number DESC
    LIMIT 1
) AS s ON true
ORDER BY e.original_filename
"@
    $databaseStatuses = Invoke-DockerChecked -Arguments @(
        "exec",
        $postgresId,
        "psql",
        "-U",
        "sitara_e2e",
        "-d",
        "sitara_clamav_e2e",
        "-At",
        "-c",
        $statusSql
    ) -Quiet
    $statusLines = @($databaseStatuses -split "\r?\n" | Where-Object { $_ })
    if ($statusLines.Count -ne 2 -or
        $statusLines -notcontains "daemon-safe.txt|CLEAN|true" -or
        $statusLines -notcontains "daemon-eicar.txt|REJECTED|true") {
        throw "Disposable PostgreSQL did not contain the expected terminal scan states and checksums"
    }
    Write-Host "Disposable PostgreSQL scan rows: $($statusLines -join ', ')"

    $daemonLogs = Invoke-DockerChecked -Arguments @("logs", $daemonWorkerId) -Quiet
    $cleanLogCount = [regex]::Matches($daemonLogs, "Evidence scan completed; evidence_id=.*result=CLEAN").Count
    $rejectedLogCount = [regex]::Matches($daemonLogs, "Evidence scan completed; evidence_id=.*result=REJECTED").Count
    if ($cleanLogCount -ne 1 -or $rejectedLogCount -ne 1) {
        throw "Recovery daemon logs did not show exactly one CLEAN and one REJECTED result"
    }
    Write-Host "Recovery daemon log results: CLEAN=$cleanLogCount, REJECTED=$rejectedLogCount"
}
catch {
    $mainError = $_
}
finally {
    $cleanupContainerIds = $createdContainerIds.ToArray()
    [array]::Reverse($cleanupContainerIds)
    foreach ($containerId in $cleanupContainerIds) {
        if (-not $containerId) {
            continue
        }
        try {
            $state = Get-ContainerStatus -ContainerId $containerId
            if ($postgresId -and $containerId -eq $postgresId) {
                if ($state -eq "running") {
                    $null = Invoke-DockerChecked -Arguments @("stop", "--time", "5", $containerId) -Quiet
                }
                continue
            }
            if ($state -eq "running") {
                $null = Invoke-DockerChecked -Arguments @("stop", "--time", "5", $containerId) -Quiet
            }
            $state = Get-ContainerStatus -ContainerId $containerId
            if ($state -in @("created", "exited", "dead")) {
                $null = Invoke-DockerChecked -Arguments @("rm", $containerId) -Quiet
            }
        }
        catch {
            if ($postgresId -and $containerId -eq $postgresId) {
                # The PostgreSQL container uses --rm, so stopping it removes its tmpfs-backed database.
                try {
                    & docker inspect $postgresId 2>$null | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        & docker stop --time 5 $postgresId 2>$null | Out-Null
                    }
                }
                catch {
                    $cleanupErrors.Add("could not stop the disposable PostgreSQL container")
                }
            }
            else {
                $cleanupErrors.Add("could not remove disposable container $containerId")
            }
        }
    }

    if ($testRunnerImageCreated -and $testRunnerImage) {
        try {
            $null = Invoke-DockerChecked -Arguments @("image", "rm", $testRunnerImage) -Quiet
        }
        catch {
            $cleanupErrors.Add("could not remove the disposable pytest runner image")
        }
    }
    if ($workerBaseTagCreated -and $workerBaseTag) {
        try {
            $null = Invoke-DockerChecked -Arguments @("image", "rm", $workerBaseTag) -Quiet
        }
        catch {
            $cleanupErrors.Add("could not remove the temporary worker base image tag")
        }
    }

    if ($clamavConnected -and $testNetwork) {
        try {
            $null = Invoke-DockerChecked -Arguments @(
                "network",
                "disconnect",
                $testNetwork,
                $clamavContainerId
            ) -Quiet
        }
        catch {
            $cleanupErrors.Add("could not disconnect the existing ClamAV container from the test network")
        }
    }
    if ($testNetworkCreated -and $testNetwork) {
        try {
            $null = Invoke-DockerChecked -Arguments @("network", "rm", $testNetwork) -Quiet
        }
        catch {
            $cleanupErrors.Add("could not remove the disposable internal Docker network")
        }
    }

    if ($devWorkerWasRunning -and $devWorkerStoppedByHarness) {
        try {
            if ((Get-ContainerStatus -ContainerId $devWorkerId) -ne "running") {
                $null = Invoke-DockerChecked -Arguments @("compose", "start", "evidence-scanner")
            }
            if ((Get-ContainerStatus -ContainerId $devWorkerId) -ne "running") {
                throw "Compose evidence-scanner did not return to running state"
            }
            Write-Host "Original Compose evidence-scanner restarted after disposable test cleanup."
        }
        catch {
            $cleanupErrors.Add("could not restore the original Compose evidence-scanner")
        }
    }

    if ($cleanupErrors.Count -eq 0) {
        Write-Host "Cleanup complete: tmpfs-backed database/evidence/control, containers, image, and network removed."
    }
    else {
        foreach ($cleanupError in $cleanupErrors) {
            Write-Warning $cleanupError
        }
    }

    Set-Location $previousLocation
}

if ($cleanupErrors.Count -gt 0) {
    throw "Disposable ClamAV E2E cleanup was incomplete"
}
if ($mainError) {
    throw $mainError
}
