# Cognito managed login branding

Kinetiq V uses Cognito managed login version 2 for browser authentication. Terraform owns the user-pool domain version. The AWS provider does not currently expose the managed-login branding API, so the visual settings and their idempotent deployment script live here.

The theme uses the product's dark surface, lime primary action, cyan focus/link states, and the transparent brand mark in the form. Both Cognito color modes receive the same logo so the forced dark theme remains visually consistent.

## Apply the theme

Authenticate with an AWS principal that can describe and update Cognito managed-login branding. From the repository root:

```powershell
$environmentPath = "infra/terraform/environments/hackathon"
$userPoolId = terraform -chdir=$environmentPath output -raw cognito_user_pool_id
$clientId = terraform -chdir=$environmentPath output -raw cognito_web_client_id

./infra/cognito/managed-login/apply.ps1 `
  -UserPoolId $userPoolId `
  -ClientId $clientId `
  -Region us-east-1
```

Run the script again after changing `settings.json` or the brand mark. The script discovers the branding identifier from the app client, uploads both color-mode logo assets, and replaces the settings in one request.
