Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:NetworkLabels = [pscustomobject]@{
    "sitara.test" = "clamav-daemon-e2e"
    "sitara.test.project" = "unique-test-project"
}
$script:ContainerLabels = [pscustomobject]@{
    "sitara.test" = "clamav-daemon-e2e"
    "sitara.test.project" = "unique-test-project"
}
$script:Internal = "true"
$script:EndpointJson = "{}"
$script:InspectionFailureAt = "none"

function Get-DockerLabels {
    param(
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Id
    )

    if ($Kind -eq "network") {
        return $script:NetworkLabels
    }
    if ($Kind -eq "container") {
        return $script:ContainerLabels
    }
    throw "Unexpected label lookup for kind '$Kind'"
}

function Invoke-DockerChecked {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Quiet
    )

    if ($Arguments[3] -eq "{{.Internal}}") {
        if ($script:InspectionFailureAt -eq "internal") {
            throw "Synthetic network internal-state inspection failure"
        }
        return $script:Internal
    }
    if ($Arguments[3] -eq "{{json .Containers}}") {
        if ($script:InspectionFailureAt -eq "containers") {
            throw "Synthetic network endpoint inspection failure"
        }
        return $script:EndpointJson
    }
    throw "Unexpected synthetic Docker inspection: $($Arguments -join ' ')"
}

function Set-TestNetwork {
    param(
        [string]$EndpointJson = "{}",
        [string]$Internal = "true",
        [ValidateSet("none", "internal", "containers")][string]$InspectionFailureAt = "none",
        [string]$ProjectLabel = "unique-test-project"
    )

    $script:EndpointJson = $EndpointJson
    $script:Internal = $Internal
    $script:InspectionFailureAt = $InspectionFailureAt
    $script:NetworkLabels = [pscustomobject]@{
        "sitara.test" = $script:ExpectedTestLabel
        "sitara.test.project" = $ProjectLabel
    }
    $script:ContainerLabels = [pscustomobject]@{
        "sitara.test" = $script:ExpectedTestLabel
        "sitara.test.project" = "unique-test-project"
    }
}

function Invoke-NetworkGuard {
    param(
        [Parameter(Mandatory = $true)][string]$GuardName,
        [bool]$RequireEmpty = $true
    )

    $parameters = @{
        NetworkName = "unique-test-network"
        ProjectName = "unique-test-project"
        ExpectedInternal = $true
        RequireEmpty = $RequireEmpty
    }
    & $GuardName @parameters
}

function Assert-GuardThrows {
    param(
        [Parameter(Mandatory = $true)][string]$GuardName,
        [bool]$RequireEmpty = $true
    )

    $threw = $false
    try {
        Invoke-NetworkGuard -GuardName $GuardName -RequireEmpty $RequireEmpty
    }
    catch {
        $threw = $true
    }
    if (-not $threw) {
        throw "Expected $GuardName to fail closed for the supplied network state"
    }
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$guardDefinitions = @(
    @{
        Path = Join-Path $repositoryRoot "backend\scripts\test-clamav-daemon-e2e.ps1"
        Name = "Assert-OwnedNetwork"
    },
    @{
        Path = Join-Path $repositoryRoot "backend\scripts\test-clamav-http-uvicorn-e2e.ps1"
        Name = "Assert-OwnedTestNetwork"
    }
)

foreach ($guardDefinition in $guardDefinitions) {
    $script:ExpectedTestLabel = if ($guardDefinition.Name -eq "Assert-OwnedNetwork") {
        "clamav-daemon-e2e"
    }
    else {
        "clamav-http-uvicorn-e2e"
    }
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $guardDefinition.Path,
        [ref]$tokens,
        [ref]$parseErrors
    )
    if ($parseErrors.Count -gt 0) {
        throw "Could not parse $($guardDefinition.Path): $($parseErrors -join '; ')"
    }
    $functionAst = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $guardDefinition.Name
    }, $true) | Select-Object -First 1
    if (-not $functionAst) {
        throw "Could not find function $($guardDefinition.Name) in $($guardDefinition.Path)"
    }
    Invoke-Expression $functionAst.Extent.Text

    Set-TestNetwork -EndpointJson "{}"
    Invoke-NetworkGuard -GuardName $guardDefinition.Name

    Set-TestNetwork -EndpointJson "null"
    Invoke-NetworkGuard -GuardName $guardDefinition.Name

    Set-TestNetwork -EndpointJson $null
    Assert-GuardThrows -GuardName $guardDefinition.Name

    Set-TestNetwork -EndpointJson '{"container-id":{}}'
    Assert-GuardThrows -GuardName $guardDefinition.Name -RequireEmpty $true
    Invoke-NetworkGuard -GuardName $guardDefinition.Name -RequireEmpty $false

    Set-TestNetwork -EndpointJson '{"container-id":{}}'
    $script:ContainerLabels.'sitara.test.project' = "another-project"
    Assert-GuardThrows -GuardName $guardDefinition.Name -RequireEmpty $false

    Set-TestNetwork -ProjectLabel "another-project"
    Assert-GuardThrows -GuardName $guardDefinition.Name

    Set-TestNetwork -Internal "false"
    Assert-GuardThrows -GuardName $guardDefinition.Name

    Set-TestNetwork -InspectionFailureAt "internal"
    Assert-GuardThrows -GuardName $guardDefinition.Name

    Set-TestNetwork -InspectionFailureAt "containers"
    Assert-GuardThrows -GuardName $guardDefinition.Name

    Set-TestNetwork -EndpointJson "not-json"
    Assert-GuardThrows -GuardName $guardDefinition.Name
}

$daemonScriptPath = Join-Path $repositoryRoot "backend\scripts\test-clamav-daemon-e2e.ps1"
$daemonTokens = $null
$daemonParseErrors = $null
$daemonAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $daemonScriptPath,
    [ref]$daemonTokens,
    [ref]$daemonParseErrors
)
if ($daemonParseErrors.Count -gt 0) {
    throw "Could not parse $daemonScriptPath`: $($daemonParseErrors -join '; ')"
}
$containerPresenceAst = $daemonAst.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Test-ContainerPresent"
}, $true) | Select-Object -First 1
if (-not $containerPresenceAst) {
    throw "Could not find Test-ContainerPresent in $daemonScriptPath"
}

$script:ContainerIds = @()
$script:ContainerListFailure = $false
function Get-DockerIds {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if ($script:ContainerListFailure) {
        throw "Synthetic container listing failure"
    }
    return ,@($script:ContainerIds)
}
Invoke-Expression $containerPresenceAst.Extent.Text

$script:ContainerIds = @()
if (Test-ContainerPresent -ContainerId "0123456789abcdef0123456789abcdef") {
    throw "A container absent from Docker's inventory was reported present"
}

$script:ContainerIds = @("0123456789abcdef0123456789abcdef")
if (-not (Test-ContainerPresent -ContainerId "0123456789abcdef")) {
    throw "An existing container ID prefix was not recognized"
}

$script:ContainerIds = @("fedcba9876543210fedcba9876543210")
$mismatchThrew = $false
try {
    Test-ContainerPresent -ContainerId "0123456789abcdef"
}
catch {
    $mismatchThrew = $true
}
if (-not $mismatchThrew) {
    throw "A mismatched container inventory result did not fail closed"
}

$script:ContainerListFailure = $true
$inspectionThrew = $false
try {
    Test-ContainerPresent -ContainerId "0123456789abcdef"
}
catch {
    $inspectionThrew = $true
}
if (-not $inspectionThrew) {
    throw "A failed Docker container inventory did not fail closed"
}

Write-Output "PASS: both network guards fail closed and handle empty/null endpoint maps"
Write-Output "PASS: daemon cleanup ignores absent container IDs and fails closed on uncertain identity"
