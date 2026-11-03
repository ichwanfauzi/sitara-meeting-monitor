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

function Get-DockerIds {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $result = Invoke-DockerChecked -Arguments $Arguments -Quiet
    return ,@($result -split "\r?\n" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
}

function Test-ContainerPresent {
    param([Parameter(Mandatory = $true)][string]$ContainerId)

    $matchingIds = Get-DockerIds -Arguments @(
        "ps", "-aq", "--no-trunc", "--filter", "id=$ContainerId"
    )
    if ($matchingIds.Count -eq 0) {
        return $false
    }
    if ($matchingIds.Count -ne 1 -or
        -not $matchingIds[0].StartsWith($ContainerId, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Docker returned an unexpected container identity while checking cleanup state"
    }
    return $true
}

function Get-DockerLabels {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("container", "network", "image")][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Id
    )

    $arguments = switch ($Kind) {
        "container" { @("inspect", "--format", "{{json .Config.Labels}}", $Id) }
        "network" { @("network", "inspect", "--format", "{{json .Labels}}", $Id) }
        "image" { @("image", "inspect", "--format", "{{json .Config.Labels}}", $Id) }
    }
    return ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments $arguments -Quiet)
}

function Assert-OwnedContainer {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$ExpectedName,
        [Parameter(Mandatory = $true)][string]$ProjectName
    )

    $name = (Invoke-DockerChecked -Arguments @(
        "inspect", "--format", "{{.Name}}", $ContainerId
    ) -Quiet).Trim().TrimStart("/")
    $labels = Get-DockerLabels -Kind container -Id $ContainerId
    if ($name -ne $ExpectedName -or
        $labels.'sitara.test' -ne "clamav-daemon-e2e" -or
        $labels.'sitara.test.project' -ne $ProjectName) {
        throw "Refusing to remove a container without matching unique E2E identity and ownership labels"
    }
}

function Assert-OwnedNetwork {
    param(
        [Parameter(Mandatory = $true)][string]$NetworkName,
        [Parameter(Mandatory = $true)][string]$ProjectName,
        [Parameter(Mandatory = $true)][bool]$ExpectedInternal,
        [switch]$RequireEmpty
    )

    $labels = Get-DockerLabels -Kind network -Id $NetworkName
    $isInternal = (Invoke-DockerChecked -Arguments @(
        "network", "inspect", "--format", "{{.Internal}}", $NetworkName
    ) -Quiet).Trim()
    if ($labels.'sitara.test' -ne "clamav-daemon-e2e" -or
        $labels.'sitara.test.project' -ne $ProjectName -or
        $isInternal -ne $ExpectedInternal.ToString().ToLowerInvariant()) {
        throw "Refusing to alter a network without matching unique E2E ownership and network type"
    }

    $endpointJson = Invoke-DockerChecked -Arguments @(
        "network", "inspect", "--format", "{{json .Containers}}", $NetworkName
    ) -Quiet
    if ([string]::IsNullOrWhiteSpace($endpointJson)) {
        throw "Could not verify the disposable network endpoint list"
    }

    $endpoints = ConvertFrom-Json -InputObject $endpointJson -ErrorAction Stop
    if ($null -eq $endpoints) {
        $endpointEntries = @()
    }
    elseif ($endpoints -is [System.Management.Automation.PSCustomObject]) {
        $endpointEntries = @($endpoints.PSObject.Properties)
    }
    else {
        throw "Disposable network endpoint inspection returned an unexpected JSON shape"
    }

    foreach ($endpoint in $endpointEntries) {
        if ([string]::IsNullOrWhiteSpace($endpoint.Name) -or $null -eq $endpoint.Value) {
            throw "Disposable network endpoint inspection returned an incomplete endpoint"
        }
        $containerLabels = Get-DockerLabels -Kind container -Id $endpoint.Name
        if ($containerLabels.'sitara.test' -ne "clamav-daemon-e2e" -or
            $containerLabels.'sitara.test.project' -ne $ProjectName) {
            throw "Refusing to alter a disposable network connected to an unowned container"
        }
    }
    if ($RequireEmpty -and $endpointEntries.Count -gt 0) {
        throw "Refusing to remove a disposable network that still has endpoints"
    }
}

function Assert-ContainerNetworks {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string[]]$ExpectedNetworkNames
    )

    $networkJson = Invoke-DockerChecked -Arguments @(
        "inspect", "--format", "{{json .NetworkSettings.Networks}}", $ContainerId
    ) -Quiet
    if ([string]::IsNullOrWhiteSpace($networkJson)) {
        throw "Could not verify the disposable container network attachments"
    }
    $networks = ConvertFrom-Json -InputObject $networkJson -ErrorAction Stop
    if ($null -eq $networks -or $networks -isnot [System.Management.Automation.PSCustomObject]) {
        throw "Disposable container network inspection returned an unexpected JSON shape"
    }

    $actualNetworkNames = @($networks.PSObject.Properties.Name | Sort-Object)
    $expectedNames = @($ExpectedNetworkNames | Sort-Object)
    if (Compare-Object -ReferenceObject $expectedNames -DifferenceObject $actualNetworkNames) {
        throw "Disposable container network attachments differ from the least-privilege expectation"
    }
}

function Assert-OwnedImage {
    param(
        [Parameter(Mandatory = $true)][string]$ImageName,
        [Parameter(Mandatory = $true)][string]$ProjectName
    )

    $labels = Get-DockerLabels -Kind image -Id $ImageName
    if ($labels.'sitara.test' -ne "clamav-daemon-e2e" -or
        $labels.'sitara.test.project' -ne $ProjectName) {
        throw "Refusing to remove an image without matching unique E2E ownership labels"
    }
    $imageId = (Invoke-DockerChecked -Arguments @(
        "image", "inspect", "--format", "{{.Id}}", $ImageName
    ) -Quiet).Trim()
    if ((Get-DockerIds -Arguments @("ps", "-aq", "--filter", "ancestor=$imageId")).Count -gt 0) {
        throw "Refusing to remove a disposable image still referenced by a container"
    }
}

function Get-ClamAVDaemonSignatureVersion {
    param([Parameter(Mandatory = $true)][string]$ContainerId)

    $versionOutput = Invoke-DockerChecked -Arguments @(
        "exec",
        $ContainerId,
        "clamdscan",
        "--config-file=/run/clamav/clamd.conf",
        "--version"
    ) -Quiet
    $match = [regex]::Match($versionOutput, "ClamAV\s+[^/]+/(\d+)/")
    if (-not $match.Success) {
        throw "Could not determine the signature version loaded by clamd"
    }
    return $match.Groups[1].Value
}

function Get-ClamAVFileSignatureVersion {
    param([Parameter(Mandatory = $true)][string]$ContainerId)

    $databaseFileName = Invoke-DockerChecked -Arguments @(
        "exec",
        $ContainerId,
        "sh",
        "-c",
        "if [ -f /var/lib/clamav/daily.cld ]; then echo daily.cld; elif [ -f /var/lib/clamav/daily.cvd ]; then echo daily.cvd; else exit 1; fi"
    ) -Quiet
    $databasePath = "/var/lib/clamav/$($databaseFileName.Trim())"
    $databaseInfo = Invoke-DockerChecked -Arguments @(
        "exec",
        $ContainerId,
        "sigtool",
        "--info",
        $databasePath
    ) -Quiet
    $match = [regex]::Match($databaseInfo, "(?m)^Version:\s*(\d+)\s*$")
    if (-not $match.Success) {
        throw "Could not determine the signature version stored in the daily database"
    }
    return $match.Groups[1].Value
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$previousLocation = Get-Location
Set-Location $repoRoot

$createdContainerIds = [System.Collections.Generic.List[string]]::new()
$cleanupErrors = [System.Collections.Generic.List[string]]::new()
$mainError = $null
$dockerVerified = $false
$testNetwork = $null
$testScannerNetwork = $null
$testEgressNetwork = $null
$testNetworkCreated = $false
$testScannerNetworkCreated = $false
$testEgressNetworkCreated = $false
$e2eBackendImage = $null
$e2eBackendImageCreated = $false
$clamavImage = $null
$clamavImageCreated = $false
$testRunnerImage = $null
$testRunnerImageCreated = $false
$clamavContainerId = $null
$postgresId = $null
$daemonWorkerId = $null

$suffix = "{0}-{1}" -f [DateTime]::UtcNow.ToString("yyyyMMddHHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$networkName = "sitara-clamav-e2e-$suffix"
$scannerNetworkName = "$networkName-scanner"
$egressNetworkName = "$networkName-egress"
$e2eProjectName = $suffix
$postgresName = "sitara-clamav-e2e-postgres-$suffix"
$daemonWorkerName = "sitara-clamav-e2e-worker-$suffix"
$clamavName = "sitara-clamav-e2e-daemon-$suffix"
$clamavPort = "3310"
$e2eBackendImage = "sitara-backend-e2e:$suffix"
$clamavImage = "sitara-clamav-e2e:$suffix"
$testRunnerImage = "sitara-clamav-e2e-runner:$suffix"
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
    $dockerVerified = $true

    $existingE2e = Get-DockerIds -Arguments @(
        "ps", "-aq", "--filter", "label=sitara.test=clamav-daemon-e2e"
    )
    if ($existingE2e.Count -gt 0) {
        throw "Another labelled disposable ClamAV daemon E2E resource is already present"
    }
    foreach ($image in @($e2eBackendImage, $clamavImage, $testRunnerImage)) {
        if ((Invoke-DockerChecked -Arguments @("image", "ls", "-q", $image) -Quiet).Trim()) {
            throw "A generated ClamAV E2E image tag already exists; refusing to overwrite it"
        }
    }

    $e2eBackendImageCreated = $true
    $null = Invoke-DockerChecked -Arguments @(
        "build",
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--label",
        "sitara.test.project=$e2eProjectName",
        "--tag",
        $e2eBackendImage,
        "--file",
        "backend/Dockerfile",
        "backend"
    )
    $clamavImageCreated = $true
    $null = Invoke-DockerChecked -Arguments @(
        "build",
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--label",
        "sitara.test.project=$e2eProjectName",
        "--build-arg",
        "CLAMAV_PORT=$clamavPort",
        "--tag",
        $clamavImage,
        "--file",
        "backend/Dockerfile.clamav",
        "backend"
    )
    $testRunnerImageCreated = $true
    Write-Host "Building a disposable pytest runner image from the dedicated E2E backend image."
    $null = Invoke-DockerChecked -Arguments @(
        "build",
        "--build-arg",
        "SITARA_WORKER_IMAGE=$e2eBackendImage",
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--label",
        "sitara.test.project=$e2eProjectName",
        "--tag",
        $testRunnerImage,
        "--file",
        "backend/Dockerfile.e2e",
        "backend"
    )
    $workerImage = (Invoke-DockerChecked -Arguments @(
        "image", "inspect", "--format", "{{.Id}}", $e2eBackendImage
    ) -Quiet).Trim()

    $alembicHeads = Invoke-DockerChecked -Arguments @(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "alembic",
        $workerImage,
        "heads"
    ) -Quiet
    if ($alembicHeads -notmatch "0011_evidence_scan_quarantine\s+\(head\)") {
        throw "The built evidence-scanner image does not contain the expected Alembic head"
    }
    Write-Host "Built evidence-scanner image migration head: 0011_evidence_scan_quarantine"

    foreach ($network in @($networkName, $scannerNetworkName, $egressNetworkName)) {
        if ((Get-DockerIds -Arguments @(
            "network", "ls", "-q", "--filter", "name=^$network$"
        )).Count -gt 0) {
            throw "A generated disposable network name already exists"
        }
    }
    $testNetwork = $networkName
    $testNetworkCreated = $true
    $testScannerNetwork = $scannerNetworkName
    $testScannerNetworkCreated = $true
    $testEgressNetwork = $egressNetworkName
    $testEgressNetworkCreated = $true
    foreach ($networkResource in @(
        @{ Name = $testNetwork; Internal = $true },
        @{ Name = $testScannerNetwork; Internal = $true },
        @{ Name = $testEgressNetwork; Internal = $false }
    )) {
        $networkArguments = @("network", "create")
        if ($networkResource.Internal) {
            $networkArguments += "--internal"
        }
        $networkArguments += @(
            "--label", "sitara.test=clamav-daemon-e2e",
            "--label", "sitara.test.project=$e2eProjectName",
            $networkResource.Name
        )
        $null = Invoke-DockerChecked -Arguments $networkArguments -Quiet
        Assert-OwnedNetwork `
            -NetworkName $networkResource.Name `
            -ProjectName $e2eProjectName `
            -ExpectedInternal $networkResource.Internal `
            -RequireEmpty
    }

    $clamavUid = (Invoke-DockerChecked -Arguments @(
        "run", "--rm", "--network", "none", "--entrypoint", "id", $clamavImage, "-u", "clamav"
    ) -Quiet).Trim()
    $clamavGid = (Invoke-DockerChecked -Arguments @(
        "run", "--rm", "--network", "none", "--entrypoint", "id", $clamavImage, "-g", "clamav"
    ) -Quiet).Trim()
    if ($clamavUid -notmatch "^\d+$" -or $clamavUid -eq "0" -or $clamavGid -notmatch "^\d+$") {
        throw "The disposable ClamAV image must provide a non-root clamav user and group"
    }

    Write-Host "Starting the disposable ClamAV daemon; only it receives temporary access to the isolated egress network."
    $clamavContainerId = (Invoke-DockerChecked -Arguments @(
        "run",
        "--detach",
        "--name",
        $clamavName,
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--label",
        "sitara.test.project=$e2eProjectName",
        "--network",
        $testEgressNetwork,
        "--tmpfs",
        "/var/lib/clamav:rw,nosuid,nodev,noexec,size=512m,uid=$clamavUid,gid=$clamavGid,mode=2755",
        "--env",
        "CLAMAV_PORT=$clamavPort",
        "--health-cmd",
        "/usr/local/bin/clamav-healthcheck",
        "--health-interval",
        "5s",
        "--health-timeout",
        "10s",
        "--health-retries",
        "5",
        "--health-start-period",
        "4m",
        $clamavImage
    ) -Quiet).Trim()
    if (-not $clamavContainerId) {
        throw "Could not start the disposable ClamAV daemon"
    }
    $createdContainerIds.Add($clamavContainerId)

    $clamavDeadline = [System.Diagnostics.Stopwatch]::StartNew()
    $clamavHealthy = $false
    while ($clamavDeadline.Elapsed.TotalSeconds -lt 360) {
        $clamavHealth = (Invoke-DockerChecked -Arguments @(
            "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", $clamavContainerId
        ) -Quiet).Trim()
        if ($clamavHealth -eq "healthy") {
            $clamavHealthy = $true
            break
        }
        if ((Get-ContainerStatus -ContainerId $clamavContainerId) -ne "running") {
            throw "Disposable ClamAV exited before its PONG healthcheck passed"
        }
        Start-Sleep -Seconds 2
    }
    if (-not $clamavHealthy) {
        throw "Disposable ClamAV did not become healthy within 360 seconds"
    }

    $clamavLabels = Get-DockerLabels -Kind container -Id $clamavContainerId
    $clamavUser = (Invoke-DockerChecked -Arguments @(
        "inspect", "--format", "{{.Config.User}}", $clamavContainerId
    ) -Quiet).Trim()
    $clamavImageId = (Invoke-DockerChecked -Arguments @(
        "inspect", "--format", "{{.Image}}", $clamavContainerId
    ) -Quiet).Trim()
    $expectedClamavImageId = (Invoke-DockerChecked -Arguments @(
        "image", "inspect", "--format", "{{.Id}}", $clamavImage
    ) -Quiet).Trim()
    $clamavPortBindings = (Invoke-DockerChecked -Arguments @(
        "inspect", "--format", "{{json .HostConfig.PortBindings}}", $clamavContainerId
    ) -Quiet).Trim()
    $clamavTmpfs = ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments @(
        "inspect", "--format", "{{json .HostConfig.Tmpfs}}", $clamavContainerId
    ) -Quiet)
    if ($clamavLabels.'sitara.test' -ne "clamav-daemon-e2e" -or
        $clamavLabels.'sitara.test.project' -ne $e2eProjectName -or
        $clamavUser -notin @("clamav", "clamav:clamav") -or
        $clamavImageId -ne $expectedClamavImageId -or
        $clamavPortBindings -notin @("{}", "null") -or
        $clamavTmpfs.PSObject.Properties.Name -notcontains "/var/lib/clamav") {
        throw "Disposable ClamAV identity, non-root runtime, tmpfs database, or host-port isolation failed"
    }
    Assert-OwnedNetwork -NetworkName $testEgressNetwork -ProjectName $e2eProjectName -ExpectedInternal $false
    Assert-ContainerNetworks -ContainerId $clamavContainerId -ExpectedNetworkNames @($testEgressNetwork)

    $daemonSignatureVersion = Get-ClamAVDaemonSignatureVersion -ContainerId $clamavContainerId
    $fileSignatureVersion = Get-ClamAVFileSignatureVersion -ContainerId $clamavContainerId
    if ($daemonSignatureVersion -ne $fileSignatureVersion) {
        $null = Invoke-DockerChecked -Arguments @(
            "exec",
            $clamavContainerId,
            "clamdscan",
            "--config-file=/run/clamav/clamd.conf",
            "--reload"
        ) -Quiet
        $signatureTimer = [System.Diagnostics.Stopwatch]::StartNew()
        while ($signatureTimer.Elapsed.TotalSeconds -lt 30) {
            Start-Sleep -Milliseconds 500
            $daemonSignatureVersion = Get-ClamAVDaemonSignatureVersion -ContainerId $clamavContainerId
            $fileSignatureVersion = Get-ClamAVFileSignatureVersion -ContainerId $clamavContainerId
            if ($daemonSignatureVersion -eq $fileSignatureVersion) {
                break
            }
        }
    }
    if ($daemonSignatureVersion -ne $fileSignatureVersion) {
        throw "Disposable ClamD did not load the current signature database"
    }

    $null = Invoke-DockerChecked -Arguments @(
        "network", "connect", "--alias", "clamav", $testScannerNetwork, $clamavContainerId
    ) -Quiet
    Assert-OwnedNetwork -NetworkName $testScannerNetwork -ProjectName $e2eProjectName -ExpectedInternal $true
    Assert-ContainerNetworks `
        -ContainerId $clamavContainerId `
        -ExpectedNetworkNames @($testScannerNetwork, $testEgressNetwork)
    $null = Invoke-DockerChecked -Arguments @(
        "network", "disconnect", $testEgressNetwork, $clamavContainerId
    ) -Quiet
    Assert-OwnedNetwork -NetworkName $testEgressNetwork -ProjectName $e2eProjectName -ExpectedInternal $false -RequireEmpty
    Assert-ContainerNetworks -ContainerId $clamavContainerId -ExpectedNetworkNames @($testScannerNetwork)
    Write-Host "Disposable ClamAV is healthy at signature version $daemonSignatureVersion; temporary egress detached."

    $postgresId = (Invoke-DockerChecked -Arguments @(
        "run",
        "--detach",
        "--rm",
        "--name",
        $postgresName,
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--label",
        "sitara.test.project=$e2eProjectName",
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
    Assert-ContainerNetworks -ContainerId $postgresId -ExpectedNetworkNames @($testNetwork)

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

    $databaseIdentity = (Invoke-DockerChecked -Arguments @(
        "exec",
        $postgresId,
        "psql",
        "-U",
        "sitara_e2e",
        "-d",
        "sitara_clamav_e2e",
        "-Atc",
        "SELECT current_database() || '|' || current_user"
    ) -Quiet).Trim()
    if ($databaseIdentity -ne "sitara_clamav_e2e|sitara_e2e") {
        throw "The disposable PostgreSQL target identity did not match the E2E database"
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

    Write-Host "Running focused worker failure and API authorization tests in a disposable container."
    $null = Invoke-DockerChecked -Arguments @(
        "run",
        "--rm",
        "--network",
        "none",
        "--mount",
        $testMount,
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "SITARA_CLAMAV_DAEMON_E2E=0",
        $testRunnerImage,
        "python",
        "-m",
        "pytest",
        "/workspace/tests/test_evidence_scanner_worker.py",
        "/workspace/tests/test_action_items.py::test_progress_evidence_upload_download_is_private_and_authorized",
        "/workspace/tests/test_action_items.py::test_super_admin_cannot_upload_or_download_evidence",
        "-q",
        "-s",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts="
    )

    $daemonWorkerId = (Invoke-DockerChecked -Arguments @(
        "run",
        "--detach",
        "--name",
        $daemonWorkerName,
        "--label",
        "sitara.test=clamav-daemon-e2e",
        "--label",
        "sitara.test.project=$e2eProjectName",
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
        "CLAMAV_PORT=$clamavPort",
        "--env",
        "CLAMAV_TIMEOUT_SECONDS=1",
        "--env",
        "EVIDENCE_SCAN_POLL_SECONDS=15",
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
    $null = Invoke-DockerChecked -Arguments @(
        "network", "connect", $testScannerNetwork, $daemonWorkerId
    ) -Quiet
    Assert-OwnedNetwork -NetworkName $testNetwork -ProjectName $e2eProjectName -ExpectedInternal $true
    Assert-OwnedNetwork -NetworkName $testScannerNetwork -ProjectName $e2eProjectName -ExpectedInternal $true
    Assert-ContainerNetworks `
        -ContainerId $daemonWorkerId `
        -ExpectedNetworkNames @($testNetwork, $testScannerNetwork)

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

    $workerStartupTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $workerLogs = ""
    while ($workerStartupTimer.Elapsed.TotalSeconds -lt 15) {
        $workerLogs = Invoke-DockerChecked -Arguments @("logs", $daemonWorkerId) -Quiet
        if ($workerLogs -match "SITARA evidence scanner worker started") {
            break
        }
        if ((Get-ContainerStatus -ContainerId $daemonWorkerId) -ne "running") {
            throw "Evidence-scanner daemon exited before its startup log was observed"
        }
        Start-Sleep -Milliseconds 200
    }
    if ($workerLogs -notmatch "SITARA evidence scanner worker started") {
        throw "Evidence-scanner daemon did not emit its startup log within 15 seconds"
    }
    Write-Host "The worker started while ClamAV was connected to the disposable network."

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
        if (Test-ContainerPath -ContainerId $daemonWorkerId -Path "$controlPath/safe-pending") {
            break
        }
        if (Test-ContainerPath -ContainerId $daemonWorkerId -Path $runnerExitPath) {
            $runnerLogs = Invoke-DockerChecked -Arguments @("exec", $daemonWorkerId, "cat", $runnerLogPath) -Quiet
            Write-Host $runnerLogs
            throw "Disposable daemon E2E runner exited before ClamAV was disconnected"
        }
        if ((Get-ContainerStatus -ContainerId $daemonWorkerId) -ne "running") {
            throw "Evidence-scanner daemon exited before the safe evidence reached PENDING"
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-ContainerPath -ContainerId $daemonWorkerId -Path "$controlPath/safe-pending")) {
        throw "Disposable daemon did not upload safe evidence and confirm PENDING within 120 seconds"
    }

    $null = Invoke-DockerChecked -Arguments @(
        "network", "disconnect", $testScannerNetwork, $clamavContainerId
    ) -Quiet
    Assert-OwnedNetwork -NetworkName $testScannerNetwork -ProjectName $e2eProjectName -ExpectedInternal $true
    Write-Host "Safe evidence is PENDING; ClamAV has now been disconnected from the disposable network."

    $outageTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $outageLogs = ""
    while ($outageTimer.Elapsed.TotalSeconds -lt 30) {
        $outageLogs = Invoke-DockerChecked -Arguments @("logs", $daemonWorkerId) -Quiet
        if ($outageLogs -match "Scanner loop failed; retrying after delay" -and
            $outageLogs -match "clamav:3310") {
            break
        }
        if (Test-ContainerPath -ContainerId $daemonWorkerId -Path $runnerExitPath) {
            $runnerLogs = Invoke-DockerChecked -Arguments @("exec", $daemonWorkerId, "cat", $runnerLogPath) -Quiet
            Write-Host $runnerLogs
            throw "Disposable daemon E2E runner exited before the scanner outage was observed"
        }
        if ((Get-ContainerStatus -ContainerId $daemonWorkerId) -ne "running") {
            throw "Evidence-scanner daemon exited during the scanner outage"
        }
        Start-Sleep -Milliseconds 200
    }
    if ($outageLogs -notmatch "Scanner loop failed; retrying after delay" -or
        $outageLogs -notmatch "clamav:3310") {
        $outageEvidenceLines = @($outageLogs -split "\r?\n" | Where-Object {
            $_ -match "SITARA evidence scanner worker started|Scanner loop failed|ConnectionError|clamav:3310"
        })
        Write-Host "Worker log evidence collected during the outage window:"
        Write-Host ($outageEvidenceLines -join [Environment]::NewLine)
        throw "Evidence-scanner did not log a ClamAV connection failure within 30 seconds"
    }
    if ($outageLogs -match "Evidence scan completed") {
        throw "Evidence-scanner unexpectedly completed a scan while ClamAV was disconnected"
    }

    $pendingStatusSql = @"
SELECT e.original_filename || '|' || s.scan_status || '|' || COALESCE(s.scanned_sha256, '')
FROM action_item_evidence AS e
JOIN LATERAL (
    SELECT scan_status, scanned_sha256
    FROM action_item_evidence_scans
    WHERE evidence_id = e.id
    ORDER BY event_number DESC
    LIMIT 1
) AS s ON true
WHERE e.original_filename = 'daemon-safe.pdf'
"@
    $pendingStatus = (Invoke-DockerChecked -Arguments @(
        "exec",
        $postgresId,
        "psql",
        "-U",
        "sitara_e2e",
        "-d",
        "sitara_clamav_e2e",
        "-At",
        "-c",
        $pendingStatusSql
    ) -Quiet).Trim()
    if ($pendingStatus -ne "daemon-safe.pdf|PENDING|") {
        throw "Disposable PostgreSQL did not keep safe evidence PENDING during the scanner outage: $pendingStatus"
    }

    $outageEvidenceLines = @($outageLogs -split "\r?\n" | Where-Object {
        $_ -match "Scanner loop failed; retrying after delay|ConnectionError|clamav:3310"
    })
    Write-Host "Observed worker connection-failure log after $([math]::Round($outageTimer.Elapsed.TotalSeconds, 1)) seconds:"
    Write-Host ($outageEvidenceLines -join [Environment]::NewLine)
    Write-Host "Disposable PostgreSQL confirms daemon-safe.pdf|PENDING| during the outage."
    $null = Invoke-DockerChecked -Arguments @(
        "network",
        "connect",
        "--alias",
        "clamav",
        $testScannerNetwork,
        $clamavContainerId
    ) -Quiet
    Assert-OwnedNetwork -NetworkName $testScannerNetwork -ProjectName $e2eProjectName -ExpectedInternal $true
    $null = Invoke-DockerChecked -Arguments @(
        "exec",
        $daemonWorkerId,
        "sh",
        "-c",
        "touch $controlPath/recovery-ready"
    ) -Quiet
    Write-Host "ClamAV reconnected to the disposable network; the same daemon process will resume polling."

    $runnerTimer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($runnerTimer.Elapsed.TotalSeconds -lt 210) {
        if (Test-ContainerPath -ContainerId $daemonWorkerId -Path $runnerExitPath) {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-ContainerPath -ContainerId $daemonWorkerId -Path $runnerExitPath)) {
        throw "Disposable API/pytest process did not finish within 210 seconds after scanner recovery"
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
        $statusLines -notcontains "daemon-safe.pdf|CLEAN|true" -or
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
    if ($dockerVerified) {
        try {
            $projectContainers = Get-DockerIds -Arguments @(
                "ps", "-aq", "--filter", "label=sitara.test.project=$e2eProjectName"
            )
            foreach ($projectContainer in $projectContainers) {
                if (-not $createdContainerIds.Contains($projectContainer)) {
                    $createdContainerIds.Add($projectContainer)
                }
            }
        }
        catch {
            $cleanupErrors.Add("could not enumerate containers carrying this invocation's unique ownership label")
        }
    }

    $cleanupContainerIds = $createdContainerIds.ToArray()
    [array]::Reverse($cleanupContainerIds)
    foreach ($containerId in $cleanupContainerIds) {
        if ($cleanupErrors.Count -gt 0) {
            break
        }
        if (-not $containerId) {
            continue
        }
        try {
            if (-not (Test-ContainerPresent -ContainerId $containerId)) {
                continue
            }
            $actualContainerName = (Invoke-DockerChecked -Arguments @(
                "inspect", "--format", "{{.Name}}", $containerId
            ) -Quiet).Trim().TrimStart("/")
            $knownNames = @($clamavName, $postgresName, $daemonWorkerName)
            if ($actualContainerName -notin $knownNames) {
                throw "Refusing to clean an E2E container whose identity is unknown to this invocation"
            }
            $expectedName = $actualContainerName
            Assert-OwnedContainer -ContainerId $containerId -ExpectedName $expectedName -ProjectName $e2eProjectName
            $state = Get-ContainerStatus -ContainerId $containerId
            if ($expectedName -eq $postgresName) {
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
                Assert-OwnedContainer -ContainerId $containerId -ExpectedName $expectedName -ProjectName $e2eProjectName
                $null = Invoke-DockerChecked -Arguments @("rm", $containerId) -Quiet
            }
        }
        catch {
            $cleanupErrors.Add("could not safely remove disposable container '$containerId': $($_.Exception.Message)")
        }
    }

    if ($cleanupErrors.Count -eq 0) {
        foreach ($networkResource in @(
            @{ Name = $testNetwork; Created = $testNetworkCreated; Internal = $true },
            @{ Name = $testScannerNetwork; Created = $testScannerNetworkCreated; Internal = $true },
            @{ Name = $testEgressNetwork; Created = $testEgressNetworkCreated; Internal = $false }
        )) {
            if ($cleanupErrors.Count -gt 0) {
                break
            }
            try {
                if (-not $networkResource.Created -or -not $networkResource.Name) {
                    continue
                }
                $existingNetwork = Get-DockerIds -Arguments @(
                    "network", "ls", "-q", "--filter", "name=^$($networkResource.Name)$"
                )
                if ($existingNetwork.Count -eq 0) {
                    continue
                }
                if ($existingNetwork.Count -ne 1) {
                    throw "Generated network name resolved to an unexpected resource"
                }
                $actualNetworkName = (Invoke-DockerChecked -Arguments @(
                    "network", "inspect", "--format", "{{.Name}}", $existingNetwork[0]
                ) -Quiet).Trim()
                if ($actualNetworkName -ne $networkResource.Name) {
                    throw "The generated network ID does not have the expected unique name"
                }
                Assert-OwnedNetwork `
                    -NetworkName $networkResource.Name `
                    -ProjectName $e2eProjectName `
                    -ExpectedInternal $networkResource.Internal `
                    -RequireEmpty
                $null = Invoke-DockerChecked -Arguments @("network", "rm", $networkResource.Name) -Quiet
            }
            catch {
                $cleanupErrors.Add(
                    "could not safely remove disposable network '$($networkResource.Name)': $($_.Exception.Message)"
                )
            }
        }
    }

    if ($cleanupErrors.Count -eq 0) {
        foreach ($imageResource in @(
            @{ Name = $testRunnerImage; Created = $testRunnerImageCreated },
            @{ Name = $clamavImage; Created = $clamavImageCreated },
            @{ Name = $e2eBackendImage; Created = $e2eBackendImageCreated }
        )) {
            if ($cleanupErrors.Count -gt 0) {
                break
            }
            try {
                if (-not $imageResource.Created -or -not $imageResource.Name) {
                    continue
                }
                $existingImage = Get-DockerIds -Arguments @("image", "ls", "-q", $imageResource.Name)
                if ($existingImage.Count -eq 0) {
                    continue
                }
                if ($existingImage.Count -ne 1) {
                    throw "Generated image tag resolved to multiple image IDs"
                }
                Assert-OwnedImage -ImageName $imageResource.Name -ProjectName $e2eProjectName
                $null = Invoke-DockerChecked -Arguments @("image", "rm", $imageResource.Name) -Quiet
            }
            catch {
                $cleanupErrors.Add(
                    "could not safely remove disposable image '$($imageResource.Name)': $($_.Exception.Message)"
                )
            }
        }
    }

    if ($cleanupErrors.Count -eq 0) {
        Write-Host "Cleanup complete: disposable containers, tmpfs-backed data, unique images, and test networks removed."
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
