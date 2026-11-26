#Requires -Version 5.1
<#
.SYNOPSIS
    One-step installer & updater for Nida Computer Use v1.1 (Google Antigravity Plugin, Skill & Global MCP Registration on Windows).
#>

$ErrorActionPreference = "Stop"

$PluginName = "nida-computer-use"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GeminiRoot = Join-Path $env:USERPROFILE ".gemini"
$AntigravityPluginsDir = Join-Path $GeminiRoot "config\plugins"
$AntigravitySkillsDir = Join-Path $GeminiRoot "config\skills"
$TargetPluginDir = Join-Path $AntigravityPluginsDir $PluginName
$TargetSkillDir = Join-Path $AntigravitySkillsDir $PluginName

Write-Host ""
Write-Host "========================================================" -ForegroundColor DarkCyan
Write-Host "  Nida Computer Use v1.1 - Antigravity Plugin Installer" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor DarkCyan
Write-Host ""

$PythonCmd = $null
foreach ($candidate in @("python", "py -3", "python3")) {
    try {
        $ver = Invoke-Expression "$candidate --version 2>&1"
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $PythonCmd = $candidate
                Write-Host "[OK] Found $ver" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Error "Python 3.10+ is required. Install via: winget install Python.Python.3.12"
    exit 1
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*src.hud_app*" -or $_.CommandLine -like "*src.state_server*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

New-Item -ItemType Directory -Force -Path $AntigravityPluginsDir | Out-Null
New-Item -ItemType Directory -Force -Path $AntigravitySkillsDir | Out-Null

$ResolvedSource = (Resolve-Path $SourceDir).Path
$ResolvedTarget = if (Test-Path $TargetPluginDir) { (Resolve-Path $TargetPluginDir).Path } else { "" }

if ($ResolvedSource -ne $ResolvedTarget) {
    Write-Host "[1/5] Copying plugin files to $TargetPluginDir ..." -ForegroundColor Yellow
    if (Test-Path $TargetPluginDir) {
        Get-ChildItem -Path $TargetPluginDir -Exclude ".venv" | Remove-Item -Recurse -Force
    } else {
        New-Item -ItemType Directory -Force -Path $TargetPluginDir | Out-Null
    }
    Get-ChildItem -Path $SourceDir -Exclude ".git", ".venv", "__pycache__" | Copy-Item -Destination $TargetPluginDir -Recurse -Force
}

Write-Host "[2/5] Registering global skill at $TargetSkillDir ..." -ForegroundColor Yellow
if (Test-Path $TargetSkillDir) { Remove-Item -Recurse -Force $TargetSkillDir }
Copy-Item -Path (Join-Path $TargetPluginDir "skills\$PluginName") -Destination $TargetSkillDir -Recurse -Force

$VenvDir = Join-Path $TargetPluginDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[3/5] Creating isolated Python virtual environment..." -ForegroundColor Yellow
    Invoke-Expression "$PythonCmd -m venv `"$VenvDir`""
}

Write-Host "[4/5] Installing/updating desktop automation, Arabic voice, and HUD packages..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $TargetPluginDir "requirements.txt") --quiet

Write-Host "[5/5] Registering nida-desktop MCP server in Google Antigravity config..." -ForegroundColor Yellow
$McpServerScript = Join-Path $TargetPluginDir "src\mcp_server.py"
$DataDir = Join-Path $env:USERPROFILE ".nida-computer-use"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$McpConfigPaths = @(
    (Join-Path $GeminiRoot "antigravity\mcp_config.json"),
    (Join-Path $GeminiRoot "config\mcp_config.json")
)

foreach ($cfgPath in $McpConfigPaths) {
    $parent = Split-Path -Parent $cfgPath
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }

    $jsonObj = $null
    if (Test-Path $cfgPath) {
        try {
            $raw = Get-Content -Path $cfgPath -Raw -Encoding UTF8
            if ($raw.Trim()) { $jsonObj = $raw | ConvertFrom-Json }
        } catch { $jsonObj = $null }
    }
    if (-not $jsonObj) { $jsonObj = [PSCustomObject]@{} }
    if (-not ($jsonObj.PSObject.Properties.Name -contains "mcpServers")) {
        $jsonObj | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
    }

    $serverEntry = [PSCustomObject]@{
        command = $VenvPython
        args    = @($McpServerScript)
        env     = [PSCustomObject]@{
            NIDA_DATA_DIR              = $DataDir
            NIDA_PLUGIN_ROOT           = $TargetPluginDir
            NIDA_PERSONAL_UNRESTRICTED = "1"
            NIDA_TTS_VOICE             = "ar-SA-HamedNeural"
            NIDA_HUD_PORT              = "8765"
        }
    }

    if ($jsonObj.mcpServers.PSObject.Properties.Name -contains "nida-desktop") {
        $jsonObj.mcpServers."nida-desktop" = $serverEntry
    } else {
        $jsonObj.mcpServers | Add-Member -NotePropertyName "nida-desktop" -NotePropertyValue $serverEntry
    }

    $jsonObj | ConvertTo-Json -Depth 10 | Set-Content -Path $cfgPath -Encoding UTF8
    Write-Host "  [OK] Registered nida-desktop in $cfgPath" -ForegroundColor Green
}

if (Get-Command "agy" -ErrorAction SilentlyContinue) {
    Write-Host "[+] Detected Antigravity CLI (agy) — validating & installing plugin..." -ForegroundColor Cyan
    & agy plugin validate "$TargetPluginDir"
    & agy plugin install "$TargetPluginDir"
}

Write-Host "[+] Running Arabic voice self-test..." -ForegroundColor Cyan
& $VenvPython -m src.cli test-voice

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  Update & Installation Complete! (تم التحديث بنجاح)" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host "IMPORTANT: Restart Google Antigravity (or click Refresh in MCP Servers) so nida-desktop connects." -ForegroundColor Yellow
Write-Host ""
