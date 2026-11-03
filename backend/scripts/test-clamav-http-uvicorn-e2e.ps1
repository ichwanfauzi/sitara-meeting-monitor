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

    return (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{.State.Status}}",
        $ContainerId
    ) -Quiet).Trim()
}

function Test-ContainerPath {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$Path
    )

    & docker exec $ContainerId test -f $Path 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
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

function Get-DockerIds {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $result = Invoke-DockerChecked -Arguments $Arguments -Quiet
    return ,@($result -split "\r?\n" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
}

function Get-DockerLabels {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("container", "network", "volume", "image")][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Id
    )

    $arguments = switch ($Kind) {
        "container" { @("inspect", "--format", "{{json .Config.Labels}}", $Id) }
        "network" { @("network", "inspect", "--format", "{{json .Labels}}", $Id) }
        "volume" { @("volume", "inspect", "--format", "{{json .Labels}}", $Id) }
        "image" { @("image", "inspect", "--format", "{{json .Config.Labels}}", $Id) }
    }
    return ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments $arguments -Quiet)
}

function Assert-OwnedComposeProject {
    param([Parameter(Mandatory = $true)][string]$ProjectName)

    $containerIds = Get-DockerIds -Arguments @(
        "ps", "-aq", "--filter", "label=com.docker.compose.project=$ProjectName"
    )
    foreach ($containerId in $containerIds) {
        $labels = Get-DockerLabels -Kind container -Id $containerId
        if ($labels.'com.docker.compose.project' -ne $ProjectName -or
            $labels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
            $labels.'sitara.test.project' -ne $ProjectName) {
            throw "Refusing to stop a container without matching disposable project ownership labels"
        }
    }
}

function Assert-OwnedEvidenceVolume {
    param(
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$ProjectName,
        [switch]$RequireUnused
    )

    $labels = Get-DockerLabels -Kind volume -Id $VolumeName
    $options = ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments @(
        "volume", "inspect", "--format", "{{json .Options}}", $VolumeName
    ) -Quiet)
    if ($labels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
        $labels.'sitara.test.project' -ne $ProjectName -or
        $labels.'com.docker.compose.project' -ne $ProjectName -or
        $labels.'com.docker.compose.volume' -ne "evidence" -or
        $options.type -ne "tmpfs" -or $options.device -ne "tmpfs" -or
        $options.o -notmatch "(^|,)size=64m(,|$)" -or
        $options.o -notmatch "(^|,)uid=10001(,|$)" -or
        $options.o -notmatch "(^|,)gid=10001(,|$)" -or
        $options.o -notmatch "(^|,)mode=0700(,|$)") {
        throw "Refusing to remove an evidence volume without matching disposable tmpfs ownership"
    }

    if ($RequireUnused) {
        $usedByContainers = Get-DockerIds -Arguments @(
            "ps", "-aq", "--filter", "volume=$VolumeName"
        )
        if ($usedByContainers.Count -gt 0) {
            throw "Refusing to remove the disposable evidence volume while a container still uses it"
        }
    }
}

function Assert-OwnedTestNetwork {
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
    $expectedInternalValue = $ExpectedInternal.ToString().ToLowerInvariant()
    if ($labels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
        $labels.'sitara.test.project' -ne $ProjectName -or $isInternal -ne $expectedInternalValue) {
        throw "Refusing to alter a network without matching disposable ownership and isolation"
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
        if ($containerLabels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
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

function Assert-OwnedTestRunner {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$ProjectName
    )

    $name = (Invoke-DockerChecked -Arguments @(
        "inspect", "--format", "{{.Name}}", $ContainerId
    ) -Quiet).Trim().TrimStart("/")
    $labels = Get-DockerLabels -Kind container -Id $ContainerId
    if ($name -ne "$ProjectName-test-runner" -or
        $labels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
        $labels.'sitara.test.project' -ne $ProjectName) {
        throw "Refusing to remove a container without matching disposable runner ownership"
    }
}

function Assert-OwnedTestImage {
    param(
        [Parameter(Mandatory = $true)][string]$ImageName,
        [Parameter(Mandatory = $true)][string]$ProjectName
    )

    $labels = Get-DockerLabels -Kind image -Id $ImageName
    if ($labels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
        $labels.'sitara.test.project' -ne $ProjectName) {
        throw "Refusing to remove an image without matching disposable runner ownership"
    }
    $imageId = (Invoke-DockerChecked -Arguments @(
        "image", "inspect", "--format", "{{.Id}}", $ImageName
    ) -Quiet).Trim()
    $users = Get-DockerIds -Arguments @("ps", "-aq", "--filter", "ancestor=$imageId")
    if ($users.Count -gt 0) {
        throw "Refusing to remove a disposable image still referenced by a container"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$previousLocation = Get-Location
Set-Location $repoRoot

$composeFile = Join-Path $repoRoot "docker-compose.e2e.yml"
$composeEnvFile = Join-Path $repoRoot ".env.example"
$composeProject = $null
$networkName = $null
$workerDbNetworkName = $null
$migrationDbNetworkName = $null
$scannerNetworkName = $null
$egressNetworkName = $null
$networkCreated = $false
$workerDbNetworkCreated = $false
$migrationDbNetworkCreated = $false
$scannerNetworkCreated = $false
$egressNetworkCreated = $false
$clamavContainerId = $null
$runnerContainerId = $null
$runnerContainerMayExist = $false
$backendImage = $null
$backendImageMayExist = $false
$clamavImage = $null
$clamavImageMayExist = $false
$evidenceVolumeName = $null
$evidenceVolumeCreated = $false
$testRunnerImage = $null
$testRunnerImageMayExist = $false
$composeStarted = $false
$mainError = $null
$cleanupErrors = [System.Collections.Generic.List[string]]::new()
$environmentNames = @(
    "SITARA_CLAMAV_HTTP_E2E_DB_PASSWORD",
    "SITARA_CLAMAV_HTTP_E2E_DATABASE_URL",
    "SITARA_CLAMAV_HTTP_E2E_LIMITER_KEY",
    "SITARA_CLAMAV_HTTP_E2E_NETWORK",
    "SITARA_CLAMAV_HTTP_E2E_WORKER_DB_NETWORK",
    "SITARA_CLAMAV_HTTP_E2E_MIGRATION_DB_NETWORK",
    "SITARA_CLAMAV_HTTP_E2E_SCANNER_NETWORK",
    "SITARA_CLAMAV_HTTP_E2E_EGRESS_NETWORK",
    "SITARA_CLAMAV_HTTP_E2E_EVIDENCE_VOLUME",
    "SITARA_CLAMAV_HTTP_E2E_PROJECT",
    "SITARA_CLAMAV_HTTP_E2E_BACKEND_IMAGE",
    "SITARA_CLAMAV_HTTP_E2E_CLAMAV_IMAGE",
    "SITARA_CLAMAV_HTTP_E2E_CLAMAV_UID",
    "SITARA_CLAMAV_HTTP_E2E_CLAMAV_GID",
    "SITARA_CLAMAV_HTTP_E2E_CLAMAV_PORT"
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$suffix = "{0}-{1}" -f [DateTime]::UtcNow.ToString("yyyyMMddHHmmss"), ([guid]::NewGuid().ToString("N"))
$composeProject = "sitara-clamav-http-e2e-$suffix"
$networkName = "$composeProject-api-db"
$workerDbNetworkName = "$composeProject-worker-db"
$migrationDbNetworkName = "$composeProject-migration-db"
$scannerNetworkName = "$composeProject-scanner"
$egressNetworkName = "$composeProject-egress"
$evidenceVolumeName = "$composeProject-evidence"
$runnerName = "$composeProject-test-runner"
$backendImage = "sitara-backend-e2e:$suffix"
$clamavImage = "sitara-clamav-e2e:$suffix"
$clamavPort = "3310"
$controlPath = "/tmp/sitara-clamav-http-e2e-control"
$databasePassword = [guid]::NewGuid().ToString("N")
$limiterKey = [guid]::NewGuid().ToString("N")
$databaseUrl = "postgresql+psycopg://sitara_e2e:$databasePassword@sitara-clamav-e2e-postgres:5432/sitara_clamav_e2e"

try {
    if (-not (Test-Path -LiteralPath $composeFile) -or -not (Test-Path -LiteralPath $composeEnvFile)) {
        throw "The HTTP E2E Compose manifest or explicit example env file is missing"
    }
    $env:SITARA_CLAMAV_HTTP_E2E_DB_PASSWORD = $databasePassword
    $env:SITARA_CLAMAV_HTTP_E2E_DATABASE_URL = $databaseUrl
    $env:SITARA_CLAMAV_HTTP_E2E_LIMITER_KEY = $limiterKey
    $env:SITARA_CLAMAV_HTTP_E2E_NETWORK = $networkName
    $env:SITARA_CLAMAV_HTTP_E2E_WORKER_DB_NETWORK = $workerDbNetworkName
    $env:SITARA_CLAMAV_HTTP_E2E_MIGRATION_DB_NETWORK = $migrationDbNetworkName
    $env:SITARA_CLAMAV_HTTP_E2E_SCANNER_NETWORK = $scannerNetworkName
    $env:SITARA_CLAMAV_HTTP_E2E_EGRESS_NETWORK = $egressNetworkName
    $env:SITARA_CLAMAV_HTTP_E2E_EVIDENCE_VOLUME = $evidenceVolumeName
    $env:SITARA_CLAMAV_HTTP_E2E_PROJECT = $composeProject
    $env:SITARA_CLAMAV_HTTP_E2E_BACKEND_IMAGE = $backendImage
    $env:SITARA_CLAMAV_HTTP_E2E_CLAMAV_IMAGE = $clamavImage
    $env:SITARA_CLAMAV_HTTP_E2E_CLAMAV_PORT = $clamavPort

    $dockerOs = (Invoke-DockerChecked -Arguments @("info", "--format", "{{.OSType}}") -Quiet).Trim()
    if ($dockerOs -ne "linux") {
        throw "The isolated HTTP E2E harness requires Linux containers"
    }

    $existingHarness = Invoke-DockerChecked -Arguments @(
        "ps",
        "-q",
        "--filter",
        "label=sitara.test=clamav-http-uvicorn-e2e"
    ) -Quiet
    if ($existingHarness.Trim()) {
        throw "Another SITARA HTTP E2E harness is already running"
    }

    foreach ($image in @($backendImage, $clamavImage)) {
        if ((Invoke-DockerChecked -Arguments @("image", "ls", "-q", $image) -Quiet).Trim()) {
            throw "A generated HTTP E2E image tag already exists; refusing to overwrite it"
        }
    }
    $backendImageMayExist = $true
    $null = Invoke-DockerChecked -Arguments @(
        "build",
        "--quiet",
        "--label",
        "sitara.test=clamav-http-uvicorn-e2e",
        "--label",
        "sitara.test.project=$composeProject",
        "--tag",
        $backendImage,
        "--file",
        "backend/Dockerfile",
        "backend"
    ) -Quiet

    $clamavImageMayExist = $true
    $null = Invoke-DockerChecked -Arguments @(
        "build",
        "--quiet",
        "--label",
        "sitara.test=clamav-http-uvicorn-e2e",
        "--label",
        "sitara.test.project=$composeProject",
        "--build-arg",
        "CLAMAV_PORT=$clamavPort",
        "--tag",
        $clamavImage,
        "--file",
        "backend/Dockerfile.clamav",
        "backend"
    ) -Quiet

    $clamavUid = (Invoke-DockerChecked -Arguments @(
        "run", "--rm", "--network", "none", "--entrypoint", "id", $clamavImage, "-u", "clamav"
    ) -Quiet).Trim()
    $clamavGid = (Invoke-DockerChecked -Arguments @(
        "run", "--rm", "--network", "none", "--entrypoint", "id", $clamavImage, "-g", "clamav"
    ) -Quiet).Trim()
    if ($clamavUid -notmatch "^\d+$" -or $clamavUid -eq "0" -or $clamavGid -notmatch "^\d+$") {
        throw "The disposable ClamAV image must provide a non-root clamav user and group"
    }
    $env:SITARA_CLAMAV_HTTP_E2E_CLAMAV_UID = $clamavUid
    $env:SITARA_CLAMAV_HTTP_E2E_CLAMAV_GID = $clamavGid

    $testRunnerImage = "sitara-clamav-http-e2e-runner:$suffix"
    $existingRunnerImage = Invoke-DockerChecked -Arguments @("image", "ls", "-q", $testRunnerImage) -Quiet
    if ($existingRunnerImage.Trim()) {
        throw "A generated HTTP E2E image tag already exists"
    }
    $testRunnerImageMayExist = $true
    $null = Invoke-DockerChecked -Arguments @(
        "build",
        "--quiet",
        "--build-arg",
        "SITARA_WORKER_IMAGE=$backendImage",
        "--label",
        "sitara.test=clamav-http-uvicorn-e2e",
        "--label",
        "sitara.test.project=$composeProject",
        "--tag",
        $testRunnerImage,
        "--file",
        "backend/Dockerfile.e2e",
        "backend"
    ) -Quiet

    $testsSource = (Join-Path $repoRoot "backend\tests").Replace("\", "/")
    $testMount = "type=bind,source=$testsSource,target=/workspace/repo/backend/tests,readonly"
    $alembicSource = (Join-Path $repoRoot "backend\alembic.ini").Replace("\", "/")
    $alembicMount = "type=bind,source=$alembicSource,target=/workspace/repo/backend/alembic.ini,readonly"
    $dockerfileSource = (Join-Path $repoRoot "backend\Dockerfile").Replace("\", "/")
    $dockerfileMount = "type=bind,source=$dockerfileSource,target=/workspace/repo/backend/Dockerfile,readonly"
    $migrationsSource = (Join-Path $repoRoot "backend\migrations").Replace("\", "/")
    $migrationsMount = "type=bind,source=$migrationsSource,target=/workspace/repo/backend/migrations,readonly"
    $clamavConfigSource = (Join-Path $repoRoot "backend\clamav").Replace("\", "/")
    $clamavConfigMount = "type=bind,source=$clamavConfigSource,target=/workspace/repo/backend/clamav,readonly"
    $composeSource = (Join-Path $repoRoot "docker-compose.e2e.yml").Replace("\", "/")
    $composeManifestMount = "type=bind,source=$composeSource,target=/workspace/repo/docker-compose.e2e.yml,readonly"
    $scriptSource = (Join-Path $repoRoot "backend\scripts\test-clamav-http-uvicorn-e2e.ps1").Replace("\", "/")
    $scriptMount = "type=bind,source=$scriptSource,target=/workspace/repo/backend/scripts/test-clamav-http-uvicorn-e2e.ps1,readonly"
    $daemonScriptSource = (Join-Path $repoRoot "backend\scripts\test-clamav-daemon-e2e.ps1").Replace("\", "/")
    $daemonScriptMount = "type=bind,source=$daemonScriptSource,target=/workspace/repo/backend/scripts/test-clamav-daemon-e2e.ps1,readonly"
    Write-Host "Running the full backend suite in an isolated container without repository .env files."
    $null = Invoke-DockerChecked -Arguments @(
        "run",
        "--rm",
        "--network",
        "none",
        "--mount",
        $testMount,
        "--mount",
        $alembicMount,
        "--mount",
        $dockerfileMount,
        "--mount",
        $migrationsMount,
        "--mount",
        $clamavConfigMount,
        "--mount",
        $composeManifestMount,
        "--mount",
        $scriptMount,
        "--mount",
        $daemonScriptMount,
        "--tmpfs",
        "/tmp`:rw,nosuid,nodev,noexec,size=1g,mode=1777",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "COVERAGE_FILE=/tmp/.coverage",
        $testRunnerImage,
        "python",
        "-m",
        "pytest",
        "-c",
        "/app/pyproject.toml",
        "/workspace/repo/backend/tests",
        "-q",
        "-p",
        "no:cacheprovider"
    )

    $composePrefix = @(
        "compose",
        "--project-name",
        $composeProject,
        "--env-file",
        $composeEnvFile,
        "--file",
        $composeFile
    )
    $composeConfigJson = Invoke-DockerChecked -Arguments ($composePrefix + @("config", "--format", "json")) -Quiet
    $composeConfig = ConvertFrom-Json -InputObject $composeConfigJson
    foreach ($serviceName in @("api", "clamav", "evidence-scanner", "migration", "sitara-clamav-e2e-postgres")) {
        $serviceConfig = $composeConfig.services.$serviceName
        if ($serviceConfig.labels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
            $serviceConfig.labels.'sitara.test.project' -ne $composeProject) {
            throw "The disposable service '$serviceName' does not carry the generated ownership labels"
        }
        if (($serviceConfig.PSObject.Properties.Name -contains "ports") -and $serviceConfig.ports) {
            throw "The disposable service '$serviceName' must not publish host ports"
        }
    }
    if ($composeConfig.services.'evidence-scanner'.deploy.replicas -ne 1 -or
        -not $composeConfig.services.'evidence-scanner'.volumes[0].read_only) {
        throw "The HTTP E2E configuration must run one read-only evidence scanner"
    }

    $existingProjectContainers = Get-DockerIds -Arguments @(
        "ps", "-aq", "--filter", "label=com.docker.compose.project=$composeProject"
    )
    $existingProjectVolumes = Get-DockerIds -Arguments @(
        "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=$composeProject"
    )
    $existingRunnerName = Get-DockerIds -Arguments @(
        "ps", "-aq", "--filter", "name=^/$runnerName$"
    )
    if ($existingProjectContainers.Count -gt 0 -or $existingProjectVolumes.Count -gt 0 -or
        $existingRunnerName.Count -gt 0) {
        throw "The generated disposable project or runner name already owns Docker resources"
    }

    foreach ($network in @(
        $networkName,
        $workerDbNetworkName,
        $migrationDbNetworkName,
        $scannerNetworkName,
        $egressNetworkName
    )) {
        $existingNetwork = Invoke-DockerChecked -Arguments @(
            "network", "ls", "-q", "--filter", "name=^$network$"
        ) -Quiet
        if ($existingNetwork.Trim()) {
            throw "A generated HTTP E2E network name already exists"
        }
    }
    $existingVolume = Invoke-DockerChecked -Arguments @("volume", "ls", "-q", "--filter", "name=^$evidenceVolumeName$") -Quiet
    if ($existingVolume.Trim()) {
        throw "The generated HTTP E2E evidence volume name already exists"
    }
    $evidenceVolumeCreated = $true

    foreach ($networkResource in @(
        @{ Name = $networkName; Internal = $true },
        @{ Name = $workerDbNetworkName; Internal = $true },
        @{ Name = $migrationDbNetworkName; Internal = $true },
        @{ Name = $scannerNetworkName; Internal = $true },
        @{ Name = $egressNetworkName; Internal = $false }
    )) {
        switch ($networkResource.Name) {
            $networkName { $networkCreated = $true }
            $workerDbNetworkName { $workerDbNetworkCreated = $true }
            $migrationDbNetworkName { $migrationDbNetworkCreated = $true }
            $scannerNetworkName { $scannerNetworkCreated = $true }
            $egressNetworkName { $egressNetworkCreated = $true }
        }
        $networkArguments = @("network", "create")
        if ($networkResource.Internal) {
            $networkArguments += "--internal"
        }
        $networkArguments += @(
            "--label",
            "sitara.test=clamav-http-uvicorn-e2e",
            "--label",
            "sitara.test.project=$composeProject",
            $networkResource.Name
        )
        $null = Invoke-DockerChecked -Arguments $networkArguments -Quiet
        Assert-OwnedTestNetwork `
            -NetworkName $networkResource.Name `
            -ProjectName $composeProject `
            -ExpectedInternal $networkResource.Internal `
            -RequireEmpty
    }

    $projectedComposeConfig = $composeConfig
    if ($projectedComposeConfig.volumes.evidence.name -ne $evidenceVolumeName -or
        $projectedComposeConfig.volumes.evidence.driver_opts.type -ne "tmpfs") {
        throw "The shared evidence volume is not the generated tmpfs volume"
    }

    Write-Host "Starting the disposable ClamAV daemon with temporary egress for signature initialization."
    $composeStarted = $true
    $null = Invoke-DockerChecked -Arguments (
        $composePrefix + @("up", "--detach", "clamav")
    ) -Quiet
    $clamavContainerId = (Invoke-DockerChecked -Arguments (
        $composePrefix + @("ps", "-q", "clamav")
    ) -Quiet).Trim()
    if (-not $clamavContainerId) {
        throw "Could not find the disposable ClamAV container"
    }
    $clamavDeadline = [System.Diagnostics.Stopwatch]::StartNew()
    $clamavHealthy = $false
    while ($clamavDeadline.Elapsed.TotalSeconds -lt 360) {
        $clamavHealth = (Invoke-DockerChecked -Arguments @(
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            $clamavContainerId
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
    if ($clamavLabels.'sitara.test' -ne "clamav-http-uvicorn-e2e" -or
        $clamavLabels.'sitara.test.project' -ne $composeProject -or
        $clamavUser -ne "clamav" -or $clamavImageId -ne $expectedClamavImageId -or
        $clamavPortBindings -notin @("{}", "null") -or
        $clamavTmpfs.PSObject.Properties.Name -notcontains "/var/lib/clamav") {
        throw "Disposable ClamAV identity, non-root runtime, tmpfs database, or host-port isolation failed"
    }
    Assert-OwnedTestNetwork -NetworkName $egressNetworkName -ProjectName $composeProject -ExpectedInternal $false
    Assert-OwnedTestNetwork -NetworkName $scannerNetworkName -ProjectName $composeProject -ExpectedInternal $true
    Assert-ContainerNetworks `
        -ContainerId $clamavContainerId `
        -ExpectedNetworkNames @($scannerNetworkName, $egressNetworkName)

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

    Assert-OwnedTestNetwork -NetworkName $scannerNetworkName -ProjectName $composeProject -ExpectedInternal $true
    $null = Invoke-DockerChecked -Arguments @(
        "network", "disconnect", $egressNetworkName, $clamavContainerId
    ) -Quiet
    Assert-OwnedTestNetwork -NetworkName $egressNetworkName -ProjectName $composeProject -ExpectedInternal $false -RequireEmpty
    Assert-ContainerNetworks -ContainerId $clamavContainerId -ExpectedNetworkNames @($scannerNetworkName)
    Write-Host "Disposable ClamAV is healthy at signature version $daemonSignatureVersion; temporary egress detached."

    Write-Host "Starting isolated tmpfs PostgreSQL and applying Alembic migrations."
    $null = Invoke-DockerChecked -Arguments (
        $composePrefix + @("up", "--detach", "sitara-clamav-e2e-postgres")
    ) -Quiet
    $postgresId = (Invoke-DockerChecked -Arguments (
        $composePrefix + @("ps", "-q", "sitara-clamav-e2e-postgres")
    ) -Quiet).Trim()
    if (-not $postgresId) {
        throw "Could not find the disposable PostgreSQL container"
    }
    $postgresTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $postgresReady = $false
    while ($postgresTimer.Elapsed.TotalSeconds -lt 60) {
        $postgresHealth = (Invoke-DockerChecked -Arguments @(
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            $postgresId
        ) -Quiet).Trim()
        if ($postgresHealth -eq "healthy") {
            $postgresReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $postgresReady) {
        throw "Disposable PostgreSQL did not become healthy"
    }
    Assert-ContainerNetworks `
        -ContainerId $postgresId `
        -ExpectedNetworkNames @($networkName, $workerDbNetworkName, $migrationDbNetworkName)
    $postgresPortBindings = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.PortBindings}}",
        $postgresId
    ) -Quiet).Trim()
    $postgresMounts = Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .Mounts}}",
        $postgresId
    ) -Quiet
    $postgresTmpfs = ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.Tmpfs}}",
        $postgresId
    ) -Quiet)
    $postgresTmpfsTargets = @($postgresTmpfs.PSObject.Properties | ForEach-Object { $_.Name })
    if ($postgresPortBindings -notin @("{}", "null") -or $postgresMounts.Trim() -ne "[]" -or
        $postgresTmpfsTargets.Count -ne 1 -or $postgresTmpfsTargets[0] -ne "/var/lib/postgresql/data") {
        throw "Disposable PostgreSQL must use tmpfs only and have no host port"
    }

    $null = Invoke-DockerChecked -Arguments ($composePrefix + @("run", "--rm", "migration"))
    $currentRevision = Invoke-DockerChecked -Arguments (
        $composePrefix + @("run", "--rm", "migration", "alembic", "current")
    ) -Quiet
    if ($currentRevision -notmatch "0011_evidence_scan_quarantine") {
        throw "The disposable HTTP E2E database is not at migration head 0011"
    }
    Write-Host "Disposable database revision: 0011_evidence_scan_quarantine."

    $null = Invoke-DockerChecked -Arguments ($composePrefix + @("up", "--detach", "api")) -Quiet
    $apiId = (Invoke-DockerChecked -Arguments ($composePrefix + @("ps", "-q", "api")) -Quiet).Trim()
    if (-not $apiId) {
        throw "Could not find the disposable Uvicorn API container"
    }
    $apiTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $apiHealthy = $false
    while ($apiTimer.Elapsed.TotalSeconds -lt 90) {
        $apiHealth = (Invoke-DockerChecked -Arguments @(
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            $apiId
        ) -Quiet).Trim()
        if ($apiHealth -eq "healthy") {
            $apiHealthy = $true
            break
        }
        if ((Get-ContainerStatus -ContainerId $apiId) -ne "running") {
            throw "The Uvicorn API container exited before becoming healthy"
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $apiHealthy) {
        throw "The Uvicorn API health endpoint did not return HTTP 200"
    }
    Assert-ContainerNetworks -ContainerId $apiId -ExpectedNetworkNames @($networkName)
    $apiPortBindings = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.PortBindings}}",
        $apiId
    ) -Quiet).Trim()
    $apiMounts = @(ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .Mounts}}",
        $apiId
    ) -Quiet))
    $apiEvidenceMount = $apiMounts | Where-Object { $_.Destination -eq "/var/lib/sitara/evidence" }
    if ($apiPortBindings -notin @("{}", "null") -or -not $apiEvidenceMount -or
        $apiEvidenceMount.Name -ne $evidenceVolumeName -or $apiEvidenceMount.RW -ne $true) {
        throw "Uvicorn API must use the isolated shared evidence storage without host port bindings"
    }
    $volumeOptions = ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments @(
        "volume",
        "inspect",
        "--format",
        "{{json .Options}}",
        $evidenceVolumeName
    ) -Quiet)
    if ($volumeOptions.type -ne "tmpfs" -or $volumeOptions.device -ne "tmpfs" -or
        $volumeOptions.o -notmatch "mode=0700") {
        throw "The shared evidence volume does not have the expected tmpfs permissions"
    }
    Assert-OwnedEvidenceVolume -VolumeName $evidenceVolumeName -ProjectName $composeProject
    Write-Host "Uvicorn API is healthy on the internal network; evidence storage is shared tmpfs."

    $testRunnerCommand = "python -m pytest -c /app/pyproject.toml /workspace/repo/backend/tests/test_action_items.py::test_clamav_http_upload_is_scanned_by_compose_worker -q -s -p no:cacheprovider -o addopts="
    $runnerContainerMayExist = $true
    $runnerContainerId = (Invoke-DockerChecked -Arguments @(
        "run",
        "--detach",
        "--name",
        $runnerName,
        "--label",
        "sitara.test=clamav-http-uvicorn-e2e",
        "--label",
        "sitara.test.project=$composeProject",
        "--network",
        $networkName,
        "--mount",
        $testMount,
        "--tmpfs",
        "$controlPath`:rw,nosuid,nodev,noexec,size=8m,uid=10001,gid=10001,mode=0700",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "DATABASE_URL=$databaseUrl",
        "--env",
        "SITARA_CLAMAV_DAEMON_E2E=1",
        "--env",
        "SITARA_CLAMAV_E2E_DATABASE_URL=$databaseUrl",
        "--env",
        "SITARA_CLAMAV_HTTP_E2E=1",
        "--env",
        "SITARA_CLAMAV_HTTP_E2E_BASE_URL=http://api:8000",
        "--env",
        "SITARA_CLAMAV_HTTP_E2E_CONTROL_PATH=$controlPath",
        "--env",
        "LOGIN_RATE_LIMIT_HMAC_KEY=$limiterKey",
        $testRunnerImage,
        "sh",
        "-c",
        $testRunnerCommand
    ) -Quiet).Trim()
    if (-not $runnerContainerId) {
        throw "Could not start the disposable HTTP E2E test runner"
    }

    $uploadTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $uploadPending = $false
    while ($uploadTimer.Elapsed.TotalSeconds -lt 120) {
        if (Test-ContainerPath -ContainerId $runnerContainerId -Path "$controlPath/upload-pending") {
            $uploadPending = $true
            break
        }
        if ((Get-ContainerStatus -ContainerId $runnerContainerId) -ne "running") {
            $runnerLogs = Invoke-DockerChecked -Arguments @("logs", $runnerContainerId) -Quiet
            Write-Host $runnerLogs
            throw "HTTP E2E test runner exited before verifying PENDING via Uvicorn"
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not $uploadPending) {
        throw "HTTP E2E test runner did not upload evidence and verify PENDING within 120 seconds"
    }

    Write-Host "HTTP upload is PENDING and download is quarantined; starting exactly one Compose worker."
    $null = Invoke-DockerChecked -Arguments (
        $composePrefix + @(
            "up", "--detach", "--no-deps", "--scale", "evidence-scanner=1", "evidence-scanner"
        )
    ) -Quiet
    $workerIds = @(
        (Invoke-DockerChecked -Arguments ($composePrefix + @("ps", "-q", "evidence-scanner")) -Quiet) -split "\r?\n" |
            Where-Object { $_ }
    )
    if ($workerIds.Count -ne 1) {
        throw "The disposable Compose project must have exactly one evidence-scanner worker"
    }
    $workerId = $workerIds[0].Trim()
    Assert-ContainerNetworks `
        -ContainerId $workerId `
        -ExpectedNetworkNames @($workerDbNetworkName, $scannerNetworkName)
    $workerUser = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{.Config.User}}",
        $workerId
    ) -Quiet).Trim()
    $workerPortBindings = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .HostConfig.PortBindings}}",
        $workerId
    ) -Quiet).Trim()
    $workerMounts = @(ConvertFrom-Json -InputObject (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{json .Mounts}}",
        $workerId
    ) -Quiet))
    $workerEvidenceMount = $workerMounts | Where-Object { $_.Destination -eq "/var/lib/sitara/evidence" }
    if ($workerUser -ne "10001:10001" -or $workerPortBindings -notin @("{}", "null") -or
        -not $workerEvidenceMount -or $workerEvidenceMount.Name -ne $evidenceVolumeName -or
        $workerEvidenceMount.RW -ne $false) {
        throw "The single evidence-scanner must be non-root, unpublished, and read-only on shared storage"
    }
    if ((Get-ContainerStatus -ContainerId $runnerContainerId) -ne "running") {
        $runnerLogs = Invoke-DockerChecked -Arguments @("logs", $runnerContainerId) -Quiet
        Write-Host $runnerLogs
        throw "HTTP E2E test runner exited before worker startup was signaled"
    }
    $null = Invoke-DockerChecked -Arguments @(
        "exec",
        $runnerContainerId,
        "touch",
        "$controlPath/worker-started"
    ) -Quiet

    $runnerTimer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($runnerTimer.Elapsed.TotalSeconds -lt 90) {
        if ((Get-ContainerStatus -ContainerId $runnerContainerId) -ne "running") {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if ((Get-ContainerStatus -ContainerId $runnerContainerId) -eq "running") {
        throw "HTTP E2E test runner did not finish within 90 seconds"
    }
    $runnerExitCode = (Invoke-DockerChecked -Arguments @(
        "inspect",
        "--format",
        "{{.State.ExitCode}}",
        $runnerContainerId
    ) -Quiet).Trim()
    $runnerLogs = Invoke-DockerChecked -Arguments @("logs", $runnerContainerId) -Quiet
    Write-Host $runnerLogs
    if ($runnerExitCode -ne "0") {
        throw "Uvicorn HTTP E2E pytest exited with code $runnerExitCode"
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
    $databaseStatuses = Invoke-DockerChecked -Arguments ($composePrefix + @(
        "exec",
        "-T",
        "sitara-clamav-e2e-postgres",
        "psql",
        "-U",
        "sitara_e2e",
        "-d",
        "sitara_clamav_e2e",
        "-At",
        "-c",
        $statusSql
    )) -Quiet
    $statusLines = @($databaseStatuses -split "\r?\n" | Where-Object { $_ })
    if ($statusLines.Count -ne 2 -or
        $statusLines -notcontains "http-safe.pdf|CLEAN|true" -or
        $statusLines -notcontains "http-eicar.txt|REJECTED|true") {
        throw "Disposable PostgreSQL does not show matching CLEAN and REJECTED HTTP evidence scans"
    }
    Write-Host "Disposable PostgreSQL confirms http-safe.pdf|CLEAN|true and http-eicar.txt|REJECTED|true."
}
catch {
    $mainError = $_
}
finally {
    if (-not $runnerContainerId -and $runnerContainerMayExist -and $runnerName) {
        try {
            $partialRunnerIds = Get-DockerIds -Arguments @(
                "ps", "-aq", "--filter", "name=^/$runnerName$"
            )
            if ($partialRunnerIds.Count -gt 1) {
                throw "Multiple containers matched the unique disposable runner name"
            }
            if ($partialRunnerIds.Count -eq 1) {
                $runnerContainerId = $partialRunnerIds[0]
            }
        }
        catch {
            $cleanupErrors.Add("could not safely identify a partially created HTTP E2E runner: $($_.Exception.Message)")
        }
    }

    if ($runnerContainerId) {
        try {
            Assert-OwnedTestRunner -ContainerId $runnerContainerId -ProjectName $composeProject
            if ((Get-ContainerStatus -ContainerId $runnerContainerId) -eq "running") {
                $null = Invoke-DockerChecked -Arguments @("stop", "--time", "5", $runnerContainerId) -Quiet
            }
            Assert-OwnedTestRunner -ContainerId $runnerContainerId -ProjectName $composeProject
            $null = Invoke-DockerChecked -Arguments @("rm", $runnerContainerId) -Quiet
        }
        catch {
            $cleanupErrors.Add("could not remove the disposable HTTP E2E test runner: $($_.Exception.Message)")
        }
    }

    if ($cleanupErrors.Count -eq 0 -and $composeStarted) {
        try {
            Assert-OwnedComposeProject -ProjectName $composeProject
            $null = Invoke-DockerChecked -Arguments @(
                "compose",
                "--project-name",
                $composeProject,
                "--env-file",
                $composeEnvFile,
                "--file",
                $composeFile,
                "down",
                "--remove-orphans"
            ) -Quiet
        }
        catch {
            $cleanupErrors.Add("could not stop the disposable HTTP E2E Compose project: $($_.Exception.Message)")
        }
    }

    if ($cleanupErrors.Count -eq 0 -and $evidenceVolumeCreated) {
        try {
            $existingVolume = Get-DockerIds -Arguments @(
                "volume",
                "ls",
                "-q",
                "--filter",
                "name=^$evidenceVolumeName$"
            )
            if ($existingVolume.Count -gt 0) {
                if ($existingVolume.Count -ne 1 -or $existingVolume[0] -ne $evidenceVolumeName) {
                    throw "The generated evidence volume name resolved to an unexpected resource"
                }
                Assert-OwnedEvidenceVolume -VolumeName $evidenceVolumeName -ProjectName $composeProject -RequireUnused
                $null = Invoke-DockerChecked -Arguments @("volume", "rm", $evidenceVolumeName) -Quiet
            }
        }
        catch {
            $cleanupErrors.Add("could not safely remove the disposable tmpfs evidence volume: $($_.Exception.Message)")
        }
    }

    foreach ($networkResource in @(
        @{ Name = $networkName; Created = $networkCreated; Internal = $true },
        @{ Name = $workerDbNetworkName; Created = $workerDbNetworkCreated; Internal = $true },
        @{ Name = $migrationDbNetworkName; Created = $migrationDbNetworkCreated; Internal = $true },
        @{ Name = $scannerNetworkName; Created = $scannerNetworkCreated; Internal = $true },
        @{ Name = $egressNetworkName; Created = $egressNetworkCreated; Internal = $false }
    )) {
        if ($cleanupErrors.Count -gt 0) {
            break
        }
        try {
            $existingNetwork = Get-DockerIds -Arguments @(
                "network", "ls", "-q", "--filter", "name=^$($networkResource.Name)$"
            )
            if ($existingNetwork.Count -gt 0) {
                if ($existingNetwork.Count -ne 1) {
                    throw "The generated network name resolved to multiple resources"
                }
                $actualNetworkName = (Invoke-DockerChecked -Arguments @(
                    "network", "inspect", "--format", "{{.Name}}", $existingNetwork[0]
                ) -Quiet).Trim()
                if ($actualNetworkName -ne $networkResource.Name) {
                    throw "The generated network ID does not have the expected unique name"
                }
                if (-not $networkResource.Created) {
                    throw "Refusing to remove a network not created by this harness"
                }
                Assert-OwnedTestNetwork `
                    -NetworkName $networkResource.Name `
                    -ProjectName $composeProject `
                    -ExpectedInternal $networkResource.Internal `
                    -RequireEmpty
                $null = Invoke-DockerChecked -Arguments @(
                    "network", "rm", $networkResource.Name
                ) -Quiet
            }
        }
        catch {
            $cleanupErrors.Add(
                "could not safely remove disposable network '$($networkResource.Name)': $($_.Exception.Message)"
            )
        }
    }

    foreach ($imageResource in @(
        @{ Name = $testRunnerImage; MayExist = $testRunnerImageMayExist },
        @{ Name = $clamavImage; MayExist = $clamavImageMayExist },
        @{ Name = $backendImage; MayExist = $backendImageMayExist }
    )) {
        if ($cleanupErrors.Count -gt 0) {
            break
        }
        try {
            if (-not $imageResource.MayExist -or -not $imageResource.Name) {
                continue
            }
            $existingImage = Get-DockerIds -Arguments @(
                "image", "ls", "-q", $imageResource.Name
            )
            if ($existingImage.Count -gt 0) {
                if ($existingImage.Count -ne 1) {
                    throw "Generated image tag resolved to multiple image IDs"
                }
                Assert-OwnedTestImage -ImageName $imageResource.Name -ProjectName $composeProject
                $null = Invoke-DockerChecked -Arguments @(
                    "image", "rm", $imageResource.Name
                ) -Quiet
            }
        }
        catch {
            $cleanupErrors.Add(
                "could not safely remove disposable image '$($imageResource.Name)': $($_.Exception.Message)"
            )
        }
    }
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
    Set-Location $previousLocation

    if ($cleanupErrors.Count -eq 0) {
        Write-Host "Cleanup complete: E2E containers, tmpfs data, uniquely tagged images, and both test networks removed."
    }
    else {
        foreach ($cleanupError in $cleanupErrors) {
            Write-Warning $cleanupError
        }
    }
}

if ($cleanupErrors.Count -gt 0) {
    $cleanupSummary = $cleanupErrors -join "; "
    if ($mainError) {
        throw "Disposable Uvicorn HTTP E2E failed: $($mainError.Exception.Message). Cleanup issues: $cleanupSummary"
    }
    throw "Disposable Uvicorn HTTP E2E cleanup was incomplete: $cleanupSummary"
}
if ($mainError) {
    throw $mainError
}
