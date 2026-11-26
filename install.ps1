#Requires -Version 5.1
<#
.SYNOPSIS
    One-step installer for Nida Computer Use (Google Antigravity Plugin & Skill on Windows).
#>

$ErrorActionPreference = "Stop"

$PluginName = "nida-computer-use"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AntigravityPluginsDir = Join-Path $env:USERPROFILE ".gemini\config\plugins"
$AntigravitySkillsDir = Join-Path $env:USERPROFILE ".gemini\config\skills"
$TargetPluginDir = Join-Path $AntigravityPluginsDir $PluginName
$TargetSkillDir = Join-Path $AntigravitySkillsDir $PluginName

Write-Host ""
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host "  Nida Computer Use - Antigravity Plugin Installer" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkCyan
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
    Write-Error "Python 3.10+ is required. Please install Python 3.11+ from python.org or winget install Python.Python.3.12"
    exit 1
}

New-Item -ItemType Directory -Force -Path $AntigravityPluginsDir | Out-Null
New-Item -ItemType Directory -Force -Path $AntigravitySkillsDir | Out-Null

if ((Resolve-Path $SourceDir).Path -ne (Resolve-Path $TargetPluginDir -ErrorAction SilentlyContinue)) {
    Write-Host "[1/4] Copying plugin files to $TargetPluginDir ..." -ForegroundColor Yellow
    if (Test-Path $TargetPluginDir) {
        Get-ChildItem -Path $TargetPluginDir -Exclude ".venv" | Remove-Item -Recurse -Force
    } else {
        New-Item -ItemType Directory -Force -Path $TargetPluginDir | Out-Null
    }
    Get-ChildItem -Path $SourceDir -Exclude ".git", ".venv", "__pycache__" | Copy-Item -Destination $TargetPluginDir -Recurse -Force
}

Write-Host "[2/4] Registering global skill at $TargetSkillDir ..." -ForegroundColor Yellow
if (Test-Path $TargetSkillDir) { Remove-Item -Recurse -Force $TargetSkillDir }
Copy-Item -Path (Join-Path $TargetPluginDir "skills\$PluginName") -Destination $TargetSkillDir -Recurse -Force

$VenvDir = Join-Path $TargetPluginDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[3/4] Creating isolated Python virtual environment..." -ForegroundColor Yellow
    Invoke-Expression "$PythonCmd -m venv `"$VenvDir`""
}

Write-Host "[4/4] Installing desktop automation, Arabic voice, and HUD dependencies..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $TargetPluginDir "requirements.txt") --quiet

if (Get-Command "agy" -ErrorAction SilentlyContinue) {
    Write-Host "[+] Detected Antigravity CLI (agy) — validating plugin..." -ForegroundColor Cyan
    & agy plugin validate "$TargetPluginDir"
    & agy plugin install "$TargetPluginDir"
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  Installation Complete! (تم التثبيت بنجاح)" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host "Plugin Path : $TargetPluginDir"
Write-Host "Skill Path  : $TargetSkillDir"
Write-Host "Restart Google Antigravity, then type:" -ForegroundColor White
Write-Host "  /nida-computer-use افتح بريدي الإلكتروني وبلغني بالصوت" -ForegroundColor Cyan
Write-Host ""
