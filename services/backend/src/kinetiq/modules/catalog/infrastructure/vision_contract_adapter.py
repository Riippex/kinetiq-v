import json
from pathlib import Path
from typing import Any

from kinetiq.modules.catalog.application.ports import VisionCapabilities


class FileBasedVisionCapabilities(VisionCapabilities):
    def __init__(self, fixture_path: Path | None = None) -> None:
        if fixture_path is None:
            from django.conf import settings

            if hasattr(settings, "REPOSITORY_ROOT"):
                repo_root = settings.REPOSITORY_ROOT
            else:
                repo_root = Path(__file__).resolve().parents[7]
            fixture_path = (
                repo_root / "contracts" / "vision" / "v1" / "fixtures" / "capabilities.v1.json"
            )
        self._fixture_path = fixture_path
        self._supported_keys: set[str] | None = None

    def _load(self) -> set[str]:
        if self._supported_keys is None:
            with open(self._fixture_path, encoding="utf-8") as file:
                data: dict[str, Any] = json.load(file)
            exercises = data.get("supported_exercises", [])
            self._supported_keys = {item["exercise_key"] for item in exercises}
        return self._supported_keys

    def get_supported_exercise_keys(self) -> set[str]:
        return set(self._load())

    def is_exercise_supported(self, exercise_key: str) -> bool:
        return exercise_key in self._load()
