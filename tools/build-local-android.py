"""Build a loopback-only local Android APK from a regular, short-path copy."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_KEYS = (
    "EXPO_PUBLIC_KINETIQ_GRAPHQL_URL",
    "EXPO_PUBLIC_COGNITO_DOMAIN",
    "EXPO_PUBLIC_COGNITO_MOBILE_CLIENT_ID",
)


def run(arguments: list[str], directory: Path, environment: dict[str, str]) -> None:
    subprocess.run(arguments, cwd=directory, env=environment, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-root",
        type=Path,
        default=(
            Path(ROOT.anchor) / "kv-local"
            if os.name == "nt"
            else Path(tempfile.gettempdir()) / "kinetiq-local-android"
        ),
    )
    args = parser.parse_args()
    build_root = args.build_root.resolve()
    if build_root == ROOT or build_root.is_relative_to(ROOT):
        parser.error("Use a separate short-path directory outside the repository.")
    values = dotenv_values(ROOT / "apps/mobile/.env.development-local")
    if any(not values.get(key) for key in PUBLIC_KEYS):
        parser.error("Run configure-local.py with --identity-file before building.")
    if values[PUBLIC_KEYS[0]] != "http://127.0.0.1:8000/graphql/":
        parser.error("This build requires the loopback API and adb port reversal.")

    marker = build_root / ".kinetiq-local-build"
    if build_root.exists() and any(build_root.iterdir()) and not marker.exists():
        parser.error("The nonempty build directory is not owned by this helper.")
    if marker.exists() and marker.read_text(encoding="utf-8") != str(ROOT):
        parser.error("The build directory belongs to a different checkout.")
    # Reuse this helper's build directory, without removing caches or local files.
    build_root.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(ROOT), encoding="utf-8")
    files = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    for filename in files:
        if not filename:
            continue
        path = Path(filename)
        if len(path.parts) > 1 and path.parts[0] not in {"apps", "packages"}:
            continue
        if filename.startswith("apps/vega/"):
            continue
        source = ROOT / path
        if source.is_file():
            destination = build_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("EXPO_PUBLIC_"):
            del environment[key]
    environment.update({key: str(values[key]) for key in PUBLIC_KEYS})
    environment.update({"EXPO_NO_DOTENV": "1", "KINETIQ_LOCAL_ANDROID_BUILD": "1"})
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        parser.error("npm must be available.")
    run([npm, "ci", "--no-audit", "--no-fund"], build_root, environment)
    mobile_root = build_root / "apps/mobile"
    expo = build_root / "node_modules/expo/bin/cli"
    run(
        ["node", str(expo), "prebuild", "--platform", "android", "--no-install"],
        mobile_root,
        environment,
    )
    android_root = mobile_root / "android"
    gradle = android_root / ("gradlew.bat" if os.name == "nt" else "gradlew")
    run(
        [str(gradle), ":app:assembleRelease", "-PreactNativeArchitectures=arm64-v8a"],
        android_root,
        environment,
    )
    output_root = ROOT / "output"
    output_root.mkdir(exist_ok=True)
    apk = output_root / "kinetiq-v-local-arm64.apk"
    shutil.copyfile(android_root / "app/build/outputs/apk/release/app-release.apk", apk)
    print(f"Local APK ready: {apk}")
    print("Reverse ports 8000 and 9000 through adb before using this build.")


if __name__ == "__main__":
    main()
