"""Create ignored local configuration without replacing cloud/mobile settings."""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".env.development-local"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--identity-file", type=Path, help="JSON Terraform outputs; kept private"
    )
    parser.add_argument("--backend-image", help="Reuse an existing local backend image")
    parser.add_argument("--vision-image", help="Reuse an existing local Vision image")
    args = parser.parse_args()
    values = {
        key: value for key, value in dotenv_values(CONFIG).items() if value is not None
    }
    for key in (
        "LOCAL_POSTGRES_PASSWORD",
        "LOCAL_REDIS_PASSWORD",
        "LOCAL_MEDIA_PASSWORD",
        "DJANGO_SECRET_KEY",
        "VISION_SERVICE_CREDENTIAL",
    ):
        values.setdefault(key, secrets.token_hex(32))
    values.update(
        {
            "DJANGO_DEBUG": "true",
            "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1,backend,host.docker.internal",
            "AWS_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "kinetiq-local",
            "AWS_SECRET_ACCESS_KEY": values["LOCAL_MEDIA_PASSWORD"],
            "AWS_EC2_METADATA_DISABLED": "true",
            "MEDIA_S3_BUCKET": "kinetiq-media-local",
            "USE_IN_MEMORY_MEDIA_STORAGE": "false",
            "MCP_RESOURCE_URL": "http://localhost:8000/mcp",
            "MCP_ALLOWED_HOSTS": "localhost:*,127.0.0.1:*,backend:*",
            "MCP_ALLOWED_ORIGINS": "http://localhost:3000",
        }
    )
    if args.identity_file:
        outputs = json.loads(args.identity_file.read_text(encoding="utf-8-sig"))

        def output(name: str) -> str:
            return str(outputs[name]["value"])

        issuer = output("cognito_issuer_url")
        jwks = output("cognito_jwks_url")
        web = output("cognito_web_client_id")
        mobile = output("cognito_mobile_client_id")
        values.update(
            {
                "COGNITO_ISSUER_URL": issuer,
                "COGNITO_JWKS_URL": jwks,
                "COGNITO_ALLOWED_CLIENT_IDS": f"{web},{mobile}",
                "COGNITO_HOSTED_UI_DOMAIN": output("cognito_hosted_ui_domain"),
                "COGNITO_WEB_CLIENT_ID": web,
                "MCP_OIDC_ISSUER": issuer,
                "MCP_OIDC_JWKS_URL": jwks,
                "MCP_OIDC_AUDIENCE": web,
                "MCP_OIDC_REQUIRED_SCOPE": "kinetiq/coach",
                "MCP_OIDC_TOKEN_USE": "access",
            }
        )
        # Opt-in file for a local development build; existing .env.local is untouched.
        mobile_values = {
            "EXPO_PUBLIC_KINETIQ_GRAPHQL_URL": "http://127.0.0.1:8000/graphql/",
            "EXPO_PUBLIC_COGNITO_DOMAIN": output("cognito_hosted_ui_domain"),
            "EXPO_PUBLIC_COGNITO_MOBILE_CLIENT_ID": mobile,
        }
        (ROOT / "apps/mobile/.env.development-local").write_text(
            "".join(f"{key}={value}\n" for key, value in mobile_values.items()),
            encoding="utf-8",
        )
    if args.backend_image:
        values["LOCAL_BACKEND_IMAGE"] = args.backend_image
    if args.vision_image:
        values["LOCAL_VISION_IMAGE"] = args.vision_image
    CONFIG.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )
    print(
        "Local configuration saved; no credentials printed. Existing secrets preserved."
    )
    if not values.get("COGNITO_ISSUER_URL"):
        print("Cognito outputs still required for authenticated local flows.")


if __name__ == "__main__":
    main()
