$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$sourceRoot = Join-Path $repoRoot '.agents/skills'
$targetRoot = Join-Path $repoRoot '.claude/skills'
Get-ChildItem -LiteralPath $sourceRoot -Directory -Filter 'kinetiq-*' | ForEach-Object {
    $destination = Join-Path $targetRoot $_.Name
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Copy-Item -LiteralPath (Join-Path $_.FullName 'SKILL.md') -Destination (Join-Path $destination 'SKILL.md')
}
