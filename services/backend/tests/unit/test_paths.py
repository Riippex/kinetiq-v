from pathlib import Path

from kinetiq.bootstrap.paths import resolve_repository_root


def test_repository_root_resolves_from_checkout_backend() -> None:
    backend_root = Path("/workspace/services/backend")

    assert resolve_repository_root(backend_root) == Path("/workspace")


def test_repository_root_falls_back_to_compact_runtime_root() -> None:
    backend_root = Path("/app")

    assert resolve_repository_root(backend_root) == backend_root


def test_repository_root_honors_explicit_runtime_path() -> None:
    assert resolve_repository_root(Path("/app"), "/runtime") == Path("/runtime").resolve()
