param([string]$PythonPath = '', [switch]$SkipWeb)
$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Push-Location -LiteralPath $taskRoot
try {
    $taskPython = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
    $taskBase = & $taskPython -c 'import sys; print(sys._base_executable)'
    if ($LASTEXITCODE -ne 0) { throw '无法运行 Python，请提供 -PythonPath 指定原生 CPython。' }
    if ($taskBase -match 'Microsoft\\WindowsApps') {
        throw 'Microsoft Store Python 的激活代理不支持进程树回收。请安装原生 CPython 后用 -PythonPath 指定其路径。'
    }
    if (!(Test-Path -LiteralPath '.venv-server\Scripts\python.exe')) {
        & $taskPython -m venv .venv-server
        if ($LASTEXITCODE -ne 0) { throw '服务环境创建失败。' }
    }
    $taskLearningPython = Join-Path $taskRoot '.venv-learning\Scripts\python.exe'
    if (Test-Path -LiteralPath $taskLearningPython) {
        $taskLearningBase = & $taskLearningPython -c 'import sys; print(sys._base_executable)'
        if ($LASTEXITCODE -ne 0) { throw '学习环境已损坏，请检查 .venv-learning。' }
        if ($taskLearningBase -match 'Microsoft\\WindowsApps') {
            $taskLearningSource = [System.IO.Path]::GetFullPath((Join-Path $taskRoot '.venv-learning'))
            $taskLearningArchive = [System.IO.Path]::GetFullPath((Join-Path $taskRoot ('.venv-learning-store-' + [DateTime]::Now.ToString('yyyyMMddHHmmss'))))
            if ($taskLearningSource -ne (Join-Path $taskRoot '.venv-learning') -or
                !( $taskLearningArchive.StartsWith($taskRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) {
                throw '学习环境迁移目标不在本项目。'
            }
            Move-Item -LiteralPath $taskLearningSource -Destination $taskLearningArchive
            Write-Host '已保留旧 Store 学习环境，改建原生解释器环境。'
        }
    }
    if (!(Test-Path -LiteralPath $taskLearningPython)) {
        & $taskPython -m venv .venv-learning
        if ($LASTEXITCODE -ne 0) { throw '学习环境创建失败。' }
    }
    & '.\.venv-server\Scripts\python.exe' -m pip install -r requirements-server.txt
    if ($LASTEXITCODE -ne 0) { throw '服务依赖安装失败。' }
    & '.\.venv-learning\Scripts\python.exe' -m pip install -r requirements-learning.txt
    if ($LASTEXITCODE -ne 0) { throw '学习依赖安装失败。' }
    if (!$SkipWeb) {
        $taskPnpm = Get-Command pnpm -ErrorAction SilentlyContinue
        if (!$taskPnpm) { throw '未找到 pnpm。请先安装 Node.js 和 pnpm，并加入 PATH。' }
        $taskPnpmPath = $taskPnpm.Source
        Push-Location -LiteralPath (Join-Path $taskRoot 'web')
        try {
            & $taskPnpmPath install --frozen-lockfile
            if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
            & $taskPnpmPath build
            if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
        } finally { Pop-Location }
    }
    Write-Host '环境准备完成。双击 启动工作台.bat 即可打开工作台。'
} finally { Pop-Location }
