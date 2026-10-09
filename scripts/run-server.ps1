param([ValidateRange(1024, 65535)][int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskRoot
$priorPort = $env:PYTHON_WORKBENCH_PORT
$taskBrowserJob = $null
try {
    if (!(Test-Path -LiteralPath '.venv-server\Scripts\python.exe') -or !(Test-Path -LiteralPath '.venv-learning\Scripts\python.exe')) {
        throw '请先双击 首次安装.bat。'
    }
    $taskLearningBase = & '.\.venv-learning\Scripts\python.exe' -c 'import sys; print(sys._base_executable)'
    if ($LASTEXITCODE -ne 0 -or $taskLearningBase -match 'Microsoft\\WindowsApps') {
        throw '学习环境不支持进程树回收，请重新运行首次安装。'
    }
    if (!(Test-Path -LiteralPath 'web\dist\index.html')) { throw '前端尚未构建，请先双击 首次安装.bat。' }
    $taskPortAvailable = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $taskPortAvailable.Start() } catch { throw "端口 $Port 已被使用。请检查已有工作台窗口，或使用 -Port 指定其他端口。" }
    finally { $taskPortAvailable.Stop() }
    $env:PYTHON_WORKBENCH_PORT = "$Port"
    $taskUrl = "http://127.0.0.1:$Port"
    Write-Host "打开 $taskUrl ，按 Ctrl+C 停止服务。"
    if (!$NoBrowser) {
        # The job has no extra visible terminal. Open only after health succeeds.
        $taskBrowserJob = Start-Job -ArgumentList $taskUrl -ScriptBlock {
            param($Url)
            for ($attempt = 0; $attempt -lt 100; $attempt++) {
                try {
                    $health = Invoke-RestMethod -Uri ($Url + '/health') -TimeoutSec 1
                    if ($health.status -eq 'ok') { Start-Process -FilePath $Url; return }
                } catch { }
                Start-Sleep -Milliseconds 100
            }
        }
    }
    & '.\.venv-server\Scripts\python.exe' -m uvicorn server.app:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "运行服务退出，代码 $LASTEXITCODE。" }
} finally {
    if ($taskBrowserJob) { Stop-Job -Job $taskBrowserJob -ErrorAction SilentlyContinue; Remove-Job -Job $taskBrowserJob -Force -ErrorAction SilentlyContinue }
    $env:PYTHON_WORKBENCH_PORT = $priorPort
    Pop-Location
}
