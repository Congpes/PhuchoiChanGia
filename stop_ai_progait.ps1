param()

$ErrorActionPreference = 'Stop'

function Show-StopMessage([string]$message, [bool]$isError = $false) {
    Add-Type -AssemblyName PresentationFramework
    $icon = if ($isError) {
        [System.Windows.MessageBoxImage]::Error
    } else {
        [System.Windows.MessageBoxImage]::Information
    }
    [System.Windows.MessageBox]::Show(
        $message,
        'AI-ProGait',
        [System.Windows.MessageBoxButton]::OK,
        $icon
    ) | Out-Null
}

try {
    $backendConnection = Get-NetTCPConnection `
        -LocalPort 8000 `
        -State Listen `
        -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($null -ne $backendConnection) {
        $status = Invoke-RestMethod `
            -Uri 'http://127.0.0.1:8000/camera-status' `
            -TimeoutSec 3
        if ($status.backendOnline -ne $true) {
            throw 'Cong 8000 khong phai backend AI-ProGait.'
        }
        if ($status.recording.active -eq $true) {
            Show-StopMessage 'Dang ghi hinh. Hay bam DUNG GHI trong ung dung truoc khi tat AI-ProGait.' $true
            exit 1
        }
        Stop-Process -Id $backendConnection.OwningProcess -ErrorAction Stop
    }

    $frontendConnection = Get-NetTCPConnection `
        -LocalPort 53210 `
        -State Listen `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $frontendConnection) {
        $frontendProcess = Get-CimInstance Win32_Process `
            -Filter "ProcessId=$($frontendConnection.OwningProcess)"
        if (
            $frontendProcess.Name -ne 'dartvm.exe' -or
            $frontendProcess.CommandLine -notlike '*--web-port*53210*'
        ) {
            throw 'Cong 53210 khong phai Flutter AI-ProGait.'
        }
        Stop-Process -Id $frontendConnection.OwningProcess -ErrorAction Stop
    }

    Show-StopMessage 'Da tat AI-ProGait va giai phong camera.'
}
catch {
    Show-StopMessage $_.Exception.Message $true
    exit 1
}
