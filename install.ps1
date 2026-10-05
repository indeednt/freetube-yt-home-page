# Installs freetube-yt-home-page for the current user (no administrator rights needed):
#   - the script and the self-contained yt-dlp, to %LOCALAPPDATA%\freetube-yt-home-page
#   - a "FreeTube Home" shortcut in the Start menu that starts FreeTube with the Home page
#   - Python, through winget, if it isn't installed yet (only after asking)
#
#   irm https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/install.ps1 | iex
# or, from a clone of the repository:
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is very slow with its progress bar
# Older Windows 10 PowerShell may not offer TLS 1.2 by default; GitHub requires it.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072

$Repo = 'https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main'
$YtDlpUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp'
$Dir = Join-Path $env:LOCALAPPDATA 'freetube-yt-home-page'
$Script = Join-Path $Dir 'freetube_home.py'

function Step($Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }

function Test-Python($Exe) {
    try {
        & $Exe -c 'import sys, sqlite3; sys.exit(sys.version_info < (3, 8))' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-Python {
    # Windows' own "python" is only a link to the Microsoft Store unless Python is
    # installed; every candidate is tried rather than trusted.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $exe = & py -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { $candidates += $exe.Trim() }
        } catch {}
    }
    foreach ($name in 'python', 'python3') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }
    foreach ($root in "$env:LOCALAPPDATA\Programs\Python", $env:ProgramFiles) {
        if ($root -and (Test-Path $root)) {
            $candidates += Get-ChildItem -Path $root -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'python.exe' } |
                Where-Object { Test-Path $_ }
        }
    }
    foreach ($exe in $candidates) { if (Test-Python $exe) { return $exe } }
    return $null
}

function Find-FreeTube {
    $places = @(
        "$env:LOCALAPPDATA\Programs\FreeTube\FreeTube.exe",
        "$env:ProgramFiles\FreeTube\FreeTube.exe",
        "$env:USERPROFILE\scoop\apps\freetube\current\FreeTube.exe"
    )
    foreach ($p in $places) { if (Test-Path $p) { return $p } }
    $cmd = Get-Command FreeTube -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Step 'Checking FreeTube'
$FreeTube = Find-FreeTube
if ($FreeTube) {
    Write-Host "found $FreeTube"
} else {
    Write-Host 'FreeTube was not found in the usual places. Install it first, for example with:'
    Write-Host '  winget install -e --id FreeTube.FreeTube'
    Write-Host 'or from https://freetubeapp.io. For the portable version, install this anyway and then run:'
    Write-Host "  python `"$Script`" --install-launcher --freetube-path `"C:\path\to\FreeTube.exe`""
    $answer = Read-Host 'Continue anyway? [y/N]'
    if ($answer -notmatch '^[Yy]') { return }
}

Step 'Checking Python'
$Python = Find-Python
if (-not $Python) {
    Write-Host 'Python 3 is needed and was not found.'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host 'Install it now with winget (Python 3.13 from python.org, for your user only)? [Y/n]'
        if ($answer -notmatch '^[Nn]') {
            winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
            $Python = Find-Python
        }
    }
    if (-not $Python) {
        throw 'Python 3.8 or newer is needed: install it from https://www.python.org/downloads/windows/ and run this installer again.'
    }
}
Write-Host "using $Python"

Step "Installing the script to $Dir"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
# Run from a clone: use the script next to this file. Piped into iex: download it.
$local = if ($PSScriptRoot) { Join-Path $PSScriptRoot 'freetube_home.py' } else { $null }
if ($local -and (Test-Path $local)) {
    Copy-Item $local "$Script.new" -Force
    Write-Host "copied from $PSScriptRoot"
} else {
    Invoke-WebRequest -UseBasicParsing -Uri "$Repo/freetube_home.py" -OutFile "$Script.new"
    Write-Host "downloaded from $Repo"
}
& $Python -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding=''utf-8'').read())' "$Script.new"
if ($LASTEXITCODE -ne 0) { throw 'The downloaded script is damaged; please try again.' }
Move-Item "$Script.new" $Script -Force

Step 'Checking yt-dlp'
$YtDlp = Join-Path $Dir 'yt-dlp'
if (Test-Path $YtDlp) {
    Write-Host "using $YtDlp (the launcher keeps it up to date)"
} else {
    # The self-contained Python build: usable as a library (needed for the topic
    # chips), and the launcher can update it by itself.
    Write-Host "downloading the self-contained yt-dlp to $YtDlp"
    Invoke-WebRequest -UseBasicParsing -Uri $YtDlpUrl -OutFile "$YtDlp.new"
    Move-Item "$YtDlp.new" $YtDlp -Force
}

Step 'Adding a "FreeTube Home" shortcut to the Start menu'
$launcherArgs = @($Script, '--install-launcher')
if ($FreeTube) { $launcherArgs += @('--freetube-path', $FreeTube) }
& $Python @launcherArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host 'The shortcut could not be created. You can start FreeTube with the Home page by running:'
    Write-Host "  `"$Python`" `"$Script`" --launch"
}

Step 'Checking your setup'
& $Python $Script --check
if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host 'Done. Start FreeTube with "FreeTube Home" from the Start menu; "Home" appears at the top of its sidebar.'
    Write-Host 'If FreeTube is open, quit it completely first (also from the tray, if you use it).'
} else {
    Write-Host ''
    Write-Host 'Installed, but the item marked above needs fixing before the Home page can load.'
    Write-Host "Run this to re-check:  `"$Python`" `"$Script`" --check"
}
Write-Host ''
Write-Host 'Please read the Privacy section of the README:'
Write-Host '  https://github.com/indeednt/freetube-yt-home-page#privacy'
