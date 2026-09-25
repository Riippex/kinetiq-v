[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $UserPoolId,

    [Parameter(Mandatory = $true)]
    [string] $ClientId,

    [string] $Region = "us-east-1",
    [string] $Profile,
    [string] $SettingsPath = (Join-Path $PSScriptRoot "settings.json"),
    [string] $LogoPath = (Join-Path $PSScriptRoot "../../../apps/mobile/assets/images/brand-mark.png")
)

$ErrorActionPreference = "Stop"

$settingsFile = (Resolve-Path -LiteralPath $SettingsPath).Path
$logoFile = (Resolve-Path -LiteralPath $LogoPath).Path
$settings = Get-Content -LiteralPath $settingsFile -Raw | ConvertFrom-Json
$logoBytes = [System.IO.File]::ReadAllBytes($logoFile)

$describeArgs = @(
    "cognito-idp",
    "describe-managed-login-branding-by-client",
    "--user-pool-id", $UserPoolId,
    "--client-id", $ClientId,
    "--region", $Region,
    "--output", "json"
)

if ($Profile) {
    $describeArgs += @("--profile", $Profile)
}

$branding = (& aws @describeArgs | ConvertFrom-Json).ManagedLoginBranding
if (-not $branding.ManagedLoginBrandingId) {
    throw "No managed-login branding exists for client '$ClientId'. Create the default branding before applying this theme."
}

$request = [ordered]@{
    UserPoolId                = $UserPoolId
    ManagedLoginBrandingId    = $branding.ManagedLoginBrandingId
    UseCognitoProvidedValues  = $false
    Settings                  = $settings
    Assets                    = @(
        [ordered]@{
            Category  = "FORM_LOGO"
            ColorMode = "DARK"
            Extension = "PNG"
            Bytes     = [Convert]::ToBase64String($logoBytes)
        },
        [ordered]@{
            Category  = "FORM_LOGO"
            ColorMode = "LIGHT"
            Extension = "PNG"
            Bytes     = [Convert]::ToBase64String($logoBytes)
        }
    )
}

$requestPath = Join-Path ([System.IO.Path]::GetTempPath()) "kinetiq-managed-login-$([Guid]::NewGuid().ToString('N')).json"

try {
    $request | ConvertTo-Json -Depth 50 -Compress | Set-Content -LiteralPath $requestPath -Encoding utf8
    $requestUri = "file://$($requestPath.Replace('\', '/'))"
    $updateArgs = @(
        "cognito-idp",
        "update-managed-login-branding",
        "--cli-input-json", $requestUri,
        "--region", $Region,
        "--query", "ManagedLoginBranding.{ManagedLoginBrandingId:ManagedLoginBrandingId,UserPoolId:UserPoolId,UseCognitoProvidedValues:UseCognitoProvidedValues,LastModifiedDate:LastModifiedDate}",
        "--output", "json"
    )

    if ($Profile) {
        $updateArgs += @("--profile", $Profile)
    }

    & aws @updateArgs
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI failed to update the managed-login branding."
    }
}
finally {
    Remove-Item -LiteralPath $requestPath -Force -ErrorAction SilentlyContinue
}
