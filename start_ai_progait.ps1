param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend_app'
$backendPython = Join-Path $backendRoot 'venv\Scripts\python.exe'
$frontendPort = 53210
$backendUrl = 'http://127.0.0.1:8000/patients'
$frontendUrl = "http://127.0.0.1:$frontendPort"

function Show-LauncherError([string]$message) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        $message,
        'AI-ProGait',
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Error
    ) | Out-Null
}

function Test-WebEndpoint([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-WebEndpoint([string]$url, [int]$timeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($timeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-WebEndpoint $url) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$launcherMutex = New-Object System.Threading.Mutex($false, 'Local\AIProGaitLauncher')
$hasLock = $false
try {
    $hasLock = $launcherMutex.WaitOne(0, $false)
    if (-not $hasLock) {
        exit 0
    }

    if (-not (Test-Path -LiteralPath $backendPython)) {
        Show-LauncherError "Khong tim thay moi truong Python:`n$backendPython"
        exit 1
    }

    if (-not (Test-WebEndpoint $backendUrl)) {
        $matplotlibRoot = Join-Path $backendRoot '.matplotlib'
        New-Item -ItemType Directory -Path $matplotlibRoot -Force | Out-Null
        $env:SINGLE_CAMERA_MODE = 'false'
        $env:CAMERA_FRONTAL_INDEX = ''
        $env:CAMERA_SAGITTAL_INDEX = ''
        $env:FSR_SERIAL_AUTO = 'true'
        $env:FSR_SERIAL_RETRY_INITIAL_SECONDS = '0.5'
        $env:FSR_SERIAL_RETRY_MAX_SECONDS = '5'
        $env:MPLCONFIGDIR = $matplotlibRoot

        Start-Process `
            -FilePath $backendPython `
            -ArgumentList 'main.py' `
            -WorkingDirectory $backendRoot `
            -WindowStyle Hidden

        if (-not (Wait-WebEndpoint $backendUrl 45)) {
            Show-LauncherError 'Backend khong khoi dong duoc trong 45 giay. Hay kiem tra backend\venv va cong 8000.'
            exit 1
        }
    }

    if (Test-WebEndpoint $frontendUrl) {
        Start-Process $frontendUrl
        exit 0
    }

    $flutterCommand = Get-Command flutter -ErrorAction SilentlyContinue
    if ($null -eq $flutterCommand) {
        Show-LauncherError 'Khong tim thay lenh Flutter trong PATH.'
        exit 1
    }

    $packageConfig = Join-Path $frontendRoot '.dart_tool\package_config.json'
    if (-not (Test-Path -LiteralPath $packageConfig)) {
        $pubGet = Start-Process `
            -FilePath $flutterCommand.Source `
            -ArgumentList @('pub', 'get') `
            -WorkingDirectory $frontendRoot `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($pubGet.ExitCode -ne 0) {
            Show-LauncherError 'Khong the khoi phuc dependency Flutter.'
            exit 1
        }
    }

    Start-Process `
        -FilePath $flutterCommand.Source `
        -ArgumentList @(
            'run',
            '-d', 'chrome',
            '--no-pub',
            '--no-web-resources-cdn',
            '--web-port', $frontendPort
        ) `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Hidden
}
catch {
    Show-LauncherError $_.Exception.Message
    exit 1
}
finally {
    if ($hasLock) {
        $launcherMutex.ReleaseMutex()
    }
    $launcherMutex.Dispose()
}
