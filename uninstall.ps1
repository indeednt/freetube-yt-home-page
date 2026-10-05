# Removes freetube-yt-home-page: the "FreeTube Home" Start-menu shortcut and
# %LOCALAPPDATA%\freetube-yt-home-page (the script, its yt-dlp and its cache).
# FreeTube itself, its settings and its data are not touched; neither is Python.
#
#   irm https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/uninstall.ps1 | iex
# or, from a clone of the repository:
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1

$ErrorActionPreference = 'Stop'

$Shortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\FreeTube Home.lnk'
$Dir = Join-Path $env:LOCALAPPDATA 'freetube-yt-home-page'

if (Test-Path $Shortcut) {
    Remove-Item $Shortcut -Force
    Write-Host "removed the Start-menu shortcut ($Shortcut)"
}
if (Test-Path $Dir) {
    Remove-Item $Dir -Recurse -Force
    Write-Host "removed $Dir"
}
Write-Host ''
Write-Host 'Done. If FreeTube is open, restart it to remove the Home page from the sidebar.'
