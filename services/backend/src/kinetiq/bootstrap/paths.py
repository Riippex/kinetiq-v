import os
from pathlib import Path


def resolve_repository_root(backend_root: Path, configured_root: str | None = None) -> Path:
    """Resolve repository assets in a checkout or the compact runtime image."""
    if configured_root:
        return Path(configured_root).resolve()
    if len(backend_root.parents) > 1:
        return backend_root.parents[1]
    return backend_root


BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = resolve_repository_root(
    BACKEND_ROOT,
    os.getenv("KINETIQ_REPOSITORY_ROOT"),
)
