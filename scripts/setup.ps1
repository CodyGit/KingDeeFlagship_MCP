# date: 2026-11-09 21:15
# author: cody
# description: 源码安装初始化：准备 32 位 Python、创建 .venv32、安装依赖，并生成桌面 Agent 的 MCP 配置片段

param(
    # 指定一个 32 位 python.exe（Python 3.8+）；不指定则自动查找，找不到就下载官方便携版
    [string]$PythonExe = '',
    # 删除并重建 .venv32
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root   = Split-Path -Parent $PSScriptRoot
$Venv   = Join-Path $Root '.venv32'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$Py32   = Join-Path $Root 'build\py32'
$Cache  = Join-Path $Root 'build\cache'
$MinMinor = 8

# 官方 32 位便携 Python：Python 软件基金会发布在 NuGet 的 pythonx86。版本与哈希写死，下载后必须校验
$PortableVersion = '3.11.9'
$PortableUrl     = "https://api.nuget.org/v3-flatcontainer/pythonx86/$PortableVersion/pythonx86.$PortableVersion.nupkg"
$PortableSha512  = 'YJidBjZZBczPrmjOFhDsu3nue+isj3vdE+z5YoTas4piOimOO5B8p591/VPRE5KLHiHba4Dlk1LTp35JIX8iHA=='

function Step([string]$Msg) { Write-Host "==> $Msg" -ForegroundColor Cyan }
function Fail([string]$Msg) { Write-Host "[失败] $Msg" -ForegroundColor Red; exit 1 }

# 调用原生命令：Windows PowerShell 5.1 在 Stop 模式下会把 stderr 输出当成异常，这里临时放宽并统一取退出码
function Invoke-Native([string]$Exe, [string[]]$ArgList) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& $Exe @ArgList 2>&1 | ForEach-Object { "$_" })
        return @{ Code = $LASTEXITCODE; Out = $out }
    } finally {
        $ErrorActionPreference = $old
    }
}

# 返回 @{Bits; Major; Minor}；不可执行或不是 Python 时返回 $null
function Get-PyInfo([string]$Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $null }
    try {
        $r = Invoke-Native $Exe @('-c', "import struct,sys;print(struct.calcsize('P')*8,sys.version_info[0],sys.version_info[1])")
    } catch { return $null }
    if ($r.Code -ne 0 -or $r.Out.Count -eq 0) { return $null }
    $p = $r.Out[-1].Trim().Split(' ')
    if ($p.Count -ne 3) { return $null }
    return @{ Bits = [int]$p[0]; Major = [int]$p[1]; Minor = [int]$p[2] }
}

function Test-Usable($Info) {
    return ($Info -and $Info.Bits -eq 32 -and $Info.Major -eq 3 -and $Info.Minor -ge $MinMinor)
}

function Find-Python32 {
    $cands = New-Object System.Collections.Generic.List[string]
    $cands.Add((Join-Path $Py32 'tools\python.exe'))
    try {
        $r = Invoke-Native 'py' @('-0p')
        foreach ($l in $r.Out) { if ($l -match '([A-Za-z]:\\.*?python\.exe)') { $cands.Add($Matches[1]) } }
    } catch { }
    $globs = @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*-32\python.exe'), 'C:\Python3*-32\python.exe')
    foreach ($g in $globs) {
        foreach ($f in @(Get-ChildItem -Path $g -ErrorAction SilentlyContinue)) { $cands.Add($f.FullName) }
    }
    foreach ($c in $cands) { if (Test-Usable (Get-PyInfo $c)) { return $c } }
    return $null
}

function Get-Sha512Base64([string]$Path) {
    $sha = [System.Security.Cryptography.SHA512]::Create()
    try { return [Convert]::ToBase64String($sha.ComputeHash([IO.File]::ReadAllBytes($Path))) }
    finally { $sha.Dispose() }
}

function Install-Portable {
    New-Item -ItemType Directory -Force -Path $Cache | Out-Null
    $nupkg = Join-Path $Cache "pythonx86.$PortableVersion.nupkg"
    if (-not (Test-Path -LiteralPath $nupkg) -or (Get-Sha512Base64 $nupkg) -ne $PortableSha512) {
        Step "本机没有 32 位 Python，下载官方便携版 $PortableVersion（约 16MB）"
        $ProgressPreference = 'SilentlyContinue'
        try { Invoke-WebRequest -Uri $PortableUrl -OutFile $nupkg -UseBasicParsing }
        catch { Fail "下载失败：$($_.Exception.Message)`r`n可手动安装 32 位 Python 3.8+ 后用 -PythonExe 指定，或检查网络/代理。" }
    }
    if ((Get-Sha512Base64 $nupkg) -ne $PortableSha512) {
        Remove-Item -LiteralPath $nupkg -Force
        Fail '下载内容的 SHA512 与预期不符，已删除，未使用。请重试，或手动安装 32 位 Python 后用 -PythonExe 指定。'
    }
    Step "解压到 $Py32"
    if (Test-Path -LiteralPath $Py32) { Remove-Item -LiteralPath $Py32 -Recurse -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($nupkg)
    try {
        foreach ($e in $zip.Entries) {
            if ($e.FullName -notlike 'tools/*' -or $e.FullName.EndsWith('/')) { continue }
            $dest = [IO.Path]::GetFullPath((Join-Path $Py32 $e.FullName.Replace('/', '\')))
            if (-not $dest.StartsWith($Py32, [StringComparison]::OrdinalIgnoreCase)) { Fail "压缩包含越界路径：$($e.FullName)" }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
        }
    } finally { $zip.Dispose() }
    return (Join-Path $Py32 'tools\python.exe')
}

# ---------------------------------------------------------------- 1. 32 位 Python
Step '查找 32 位 Python'
if ($PythonExe) {
    if (-not (Test-Usable (Get-PyInfo $PythonExe))) { Fail "-PythonExe 指定的不是可用的 32 位 Python 3.$MinMinor+：$PythonExe" }
    $base = $PythonExe
} else {
    $base = Find-Python32
}
if (-not $base) { $base = Install-Portable }
$info = Get-PyInfo $base
if (-not (Test-Usable $info)) { Fail "无法使用 $base" }
Write-Host "    使用 $base（$($info.Bits) 位，Python $($info.Major).$($info.Minor)）"

# ---------------------------------------------------------------- 2. 虚拟环境
Step '准备虚拟环境 .venv32'
$needCreate = $true
if ((Test-Path -LiteralPath $VenvPy) -and -not $Recreate) {
    if (Test-Usable (Get-PyInfo $VenvPy)) {
        $needCreate = $false
        Write-Host '    已存在且可用，跳过创建'
    } else {
        Write-Host '    已存在但不可用（位数不对或基础解释器丢失），将重建' -ForegroundColor Yellow
    }
}
if ($needCreate) {
    if (Test-Path -LiteralPath $Venv) { Remove-Item -LiteralPath $Venv -Recurse -Force }
    $r = Invoke-Native $base @('-m', 'venv', $Venv)
    if ($r.Code -ne 0) { $r.Out | Out-Host; Fail '创建虚拟环境失败' }
}

# ---------------------------------------------------------------- 3. 依赖
Step '安装依赖（pip install -e .）'
$r = Invoke-Native $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-e', $Root)
if ($r.Code -ne 0) { $r.Out | Out-Host; Fail '依赖安装失败，请检查网络或 pip 源' }

# ---------------------------------------------------------------- 4. 验证
Step '验证环境'
$r = Invoke-Native $VenvPy @('-c', "import struct;assert struct.calcsize('P')*8==32;import win32com.client,pythoncom,win32crypt;import kingdeeflagship_mcp as k;print(k.__version__)")
if ($r.Code -ne 0) { $r.Out | Out-Host; Fail '环境验证失败：需要 32 位 Python 且已安装 pywin32' }
Write-Host "    32 位 Python + pywin32 正常，kingdeeflagship_mcp $($r.Out[-1])"

# 在临时数据目录、非项目目录下启动一次 MCP 自检，证明不依赖工作目录和 PYTHONPATH
$tmp = Join-Path $env:TEMP ('kis_setup_' + [guid]::NewGuid().ToString('N'))
$oldHome = $env:KIS_HOME
$env:KIS_HOME = $tmp
Push-Location $env:TEMP
try { $r = Invoke-Native $VenvPy @('-m', 'kingdeeflagship_mcp', 'mcp', '--self-test') }
finally {
    Pop-Location
    if ($null -eq $oldHome) { Remove-Item Env:KIS_HOME -ErrorAction SilentlyContinue } else { $env:KIS_HOME = $oldHome }
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
if ($r.Code -ne 0) { $r.Out | Out-Host; Fail 'MCP 服务自检失败' }
Write-Host '    MCP 服务自检通过'

$r = Invoke-Native $VenvPy @('-c', "import win32com.client as w;w.Dispatch('K3Login.ClsLogin')")
if ($r.Code -eq 0) { Write-Host '    检测到金蝶登录组件 K3Login' }
else { Write-Host '    [提示] 本机未检测到金蝶登录组件 K3Login，连接账套前需要先安装金蝶 KIS 客户端' -ForegroundColor Yellow }

# ---------------------------------------------------------------- 5. 配置片段
$entry = [ordered]@{ command = $VenvPy; args = @('-m', 'kingdeeflagship_mcp', 'mcp') }
$cfg   = [ordered]@{ mcpServers = [ordered]@{ 'kingdee-kis' = $entry } }
$json  = $cfg | ConvertTo-Json -Depth 5
$out   = Join-Path $Root 'build\mcp-config.json'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
[IO.File]::WriteAllText($out, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ''
Write-Host '[成功] 环境已就绪' -ForegroundColor Green
Write-Host ''
Write-Host '下一步：让桌面 Agent 关联这个 MCP。把下面 "kingdee-kis" 这一项合并进 Agent 配置的 mcpServers 中'
Write-Host '（不要整个文件覆盖，以免丢掉已有的其它 MCP），然后重启 Agent：'
Write-Host ''
Write-Host $json
Write-Host ''
Write-Host "  同样内容已保存到：$out"
Write-Host '  Claude Desktop：%APPDATA%\Claude\claude_desktop_config.json'
Write-Host '  WorkBuddy     ：%USERPROFILE%\.workbuddy\mcp.json'
Write-Host '  Kimi 桌面版   ：通过插件清单接入，见仓库 kimi 分支'
Write-Host ''
if (Test-Path -LiteralPath (Join-Path $Py32 'tools\python.exe')) {
    Write-Host '注意：build\py32 是虚拟环境的基础解释器，请不要删除；若误删，重新运行本脚本即可修复。' -ForegroundColor Yellow
}
