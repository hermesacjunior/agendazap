[CmdletBinding()]
param(
    [string]$ProjectName = "agendazap",
    [string]$Environment = "production",
    [string]$EvolutionImage = "evoapicloud/evolution-api:v2.3.7"
)

$ErrorActionPreference = "Stop"

function Invoke-Railway {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & railway.cmd @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "railway $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

if (-not (Get-Command railway.cmd -ErrorAction SilentlyContinue)) {
    throw "Railway CLI not found. Install it with: npm install -g @railway/cli"
}

try {
    Invoke-Railway whoami | Out-Null
} catch {
    Write-Host "Railway login is required. Run: railway.cmd login"
    throw
}

$projectStatus = & railway.cmd status --json 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Railway init --name $ProjectName
}

$services = @(& railway.cmd service list --json | ConvertFrom-Json)
$serviceNames = @($services | ForEach-Object { $_.name })

if ($serviceNames -notcontains "Postgres") {
    Invoke-Railway add --database postgres
}
if (-not ($serviceNames | Where-Object { $_ -like "Redis*" })) {
    Invoke-Railway add --database redis
}
if ($serviceNames -notcontains "evolution-api") {
    Invoke-Railway add --image $EvolutionImage --service evolution-api
}
if ($serviceNames -notcontains "agendazap") {
    Invoke-Railway add --service agendazap
}

$services = @(& railway.cmd service list --json | ConvertFrom-Json)
$redisService = ($services | Where-Object { $_.name -like "Redis*" } | Select-Object -First 1).name
$evolutionService = $services | Where-Object { $_.name -eq "evolution-api" } | Select-Object -First 1
if (-not $redisService -or -not $evolutionService) {
    throw "Could not resolve Redis or Evolution service after provisioning."
}

$settingsPath = Join-Path $PSScriptRoot "evolution.env.example"
$settings = Get-Content $settingsPath | Where-Object {
    $_ -and -not $_.StartsWith("#")
}

Invoke-Railway variable set --service evolution-api --environment $Environment --skip-deploys @settings
$redisReference = '${{' + $redisService + '.REDIS_URL}}'
Invoke-Railway variable set --service evolution-api --environment $Environment --skip-deploys `
    'DATABASE_CONNECTION_URI=${{Postgres.DATABASE_URL}}' `
    "CACHE_REDIS_URI=$redisReference"

$apiKey = Read-Host "Evolution API key (input hidden)" -AsSecureString
$apiKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($apiKey)
try {
    $plainApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($apiKeyPointer)
    $plainApiKey | railway.cmd variable set AUTHENTICATION_API_KEY --stdin --service evolution-api --environment $Environment --skip-deploys | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to set Evolution API key" }

    $plainApiKey | railway.cmd variable set EVOLUTION_API_KEY --stdin --service agendazap --environment $Environment --skip-deploys | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to set AgendaZap Evolution API key" }
} finally {
    if ($apiKeyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($apiKeyPointer)
    }
    $plainApiKey = $null
}

$volumeResult = & railway.cmd volume --service $evolutionService.id --environment $Environment list --json | ConvertFrom-Json
$volumes = @($volumeResult.volumes | Where-Object { $_.serviceName -eq "evolution-api" })
if ($volumes.Count -eq 0) {
    Invoke-Railway volume --service $evolutionService.id --environment $Environment add --mount-path /evolution/instances
}

Write-Host "Provisioning complete. Set SERVER_URL and EVOLUTION_API_URL after creating the Evolution public domain."
Write-Host "Deploy AgendaZap with: railway.cmd up --service agendazap --environment $Environment"
