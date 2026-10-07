# Local development and the final cloud rehearsal

Use `compose.local.yaml` for Product, real Vision inference, PostgreSQL, Redis,
and S3-compatible local photo storage. This is a separate Compose project with
separate persistent volumes. Cognito remains the managed identity provider;
local development requires internet for sign-in, but does not need AWS runtime
compute. Local records and photos are separate from the cloud environment.

## Configure

Install the locked dependencies in both sibling repositories. Start Docker
Desktop. Run from the Product root:

```powershell
services/backend/.venv/Scripts/python.exe tools/configure-local.py
```

The generated `.env.development-local` is ignored by Git. To configure identity,
save `terraform output -json` from the Product environment to an ignored private
file, then pass `--identity-file <path>` to the configuration helper. Do not
publish Terraform outputs: they may contain sensitive values. The helper prints
no credentials, preserves existing local passwords, and never replaces the
existing cloud configuration or mobile `.env.local`.

Set `enable_local_web_auth = true` in the ignored hackathon Terraform variables.
This retains the existing Cognito callback/logout URLs and adds these local URLs
through the reviewed identity configuration before testing browser authentication:

- Callback: `http://localhost:3000/api/auth/callback/cognito`
- Logout: `http://localhost:3000`

During cloud suspension, do not apply the whole active Terraform environment.
Update only the existing Cognito web client's callback/logout allowlists,
preserving every other setting, and record the change privately. Reconcile the
opt-in variable when applying the environment during the cloud rehearsal.

The mobile OAuth callback remains its existing app scheme. Do not bypass token
verification or substitute unsigned local tokens.

## Start

```powershell
docker compose --env-file .env.development-local -f compose.local.yaml up -d --build
docker compose --env-file .env.development-local -f compose.local.yaml exec backend python manage.py migrate
docker compose --env-file .env.development-local -f compose.local.yaml exec backend python manage.py seed_catalog
Get-Content tools/initialize-local-media.py -Raw | docker compose --env-file .env.development-local -f compose.local.yaml exec -T backend python -
```

Vision uses `VISION_ENV=local-real-inference`, which takes the strict real-model
branch, with the same pinned weight manifests and a service credential shared
with Product. `development` would use stub inference and is unsuitable for
camera debugging. The sibling Vision weights must be resolved before startup:

```powershell
Push-Location ../kinetiq-v-vision
.venv/Scripts/kinetiq-vision.exe resolve-weights
Pop-Location
```

Web runs the Next.js development server, so its OAuth cookies work on local
HTTP. Backend source is mounted with reload. Restart Vision after changing its
source. [Adobe S3Mock](https://github.com/adobe/S3Mock) is an isolated local S3
emulator pinned by image digest. Objects persist in a local named volume.
It does not prove AWS IAM, signature enforcement, CORS or storage-security
behavior; those remain cloud qualification checks. Use development media only.

Open `http://localhost:3000`. Backend is at `http://127.0.0.1:8000/graphql/`
and Vision readiness is at `http://127.0.0.1:8001/ready`.

Check readiness and actual local media operations:

```powershell
services/backend/.venv/Scripts/python.exe tools/verify-local.py
```

## Android device

The cloud APK continues pointing at AWS. A local development build must use the
public settings generated in `apps/mobile/.env.development-local`. Supply those
settings explicitly when building; retain the existing cloud `.env.local` for
the final cloud build. The API base URL is compiled into the bundle, so changing
a file alone does not update an installed release APK.

Build the local Android APK with Node.js on PATH, `JAVA_HOME` pointing to JDK 17,
and `ANDROID_HOME` pointing to the installed Android SDK:

```powershell
services/backend/.venv/Scripts/python.exe tools/build-local-android.py
```

The helper copies sources into a regular short directory (`C:\kv-local` on
Windows, or a temporary directory on other hosts), installs the
locked dependencies, and runs native prebuild and Gradle locally. It explicitly
loads only the public local mobile settings; cloud dotenv files are not loaded.
The result is `output/kinetiq-v-local-arm64.apk`, signed with the generated
development key and labelled **Kinetiq V Local**. It uses the existing package
and callback scheme and replaces the cloud app when installed with a compatible
signing key. It is not a store release or an iOS build.

The opt-in Expo config permits cleartext HTTP only for `127.0.0.1` and
`localhost`; other hosts, including Cognito, require HTTPS. Cloud builds do not
load that plugin. Generate cloud builds in a separate clean build directory so
previous local native resources cannot leak into their manifest.

For native Windows build failures, consult the
[Reanimated Windows build guide](https://docs.swmansion.com/react-native-reanimated/docs/guides/building-on-windows/).

For a connected device, reverse the ports. Bindings remain local to the computer:

```powershell
adb reverse tcp:8000 tcp:8000
adb reverse tcp:9000 tcp:9000
```

The internal media endpoint is `host.docker.internal:9000`; signed URLs are
generated directly for the public endpoint `127.0.0.1:9000`. This supports both
the browser and the Android device with port 9000 reversed. No signed URL is
rewritten. Cloud deployments leave `MEDIA_S3_PUBLIC_ENDPOINT_URL` unset and
continue using the default AWS endpoint.

## Stop and preserve local work

```powershell
docker compose --env-file .env.development-local -f compose.local.yaml down
```

Do not use `down -v` unless local data deletion is intended. Stopping this project
does not change AWS. Likewise, successful local tests are not AWS/device release
evidence.

## Cloud suspension and restoration

Preserve Cognito, private media, Terraform state, images, model artifacts,
restoration secrets and verified database backups. Suspension preserves resources:
save immutable task definitions, disable scheduled work and autoscaling, set ECS
desired counts to zero, and stop RDS after taking a verified snapshot. Preserve
networking and cache resources as requested by the owner; they continue billing.
Inventory both Terraform states and inspect any future restoration plan. A retained
stopped RDS instance restarts automatically after seven days and still charges
for storage; a suspension is not a promise of zero cost.

Restore the complete environment before the first submission deadline, run
migrations intentionally, validate sign-in and pairing, and repeat a real
phone-to-display session with Vision, saved results, and photos. Keep judges'
credentials, URLs, images, and the submitted version stable for judging.
