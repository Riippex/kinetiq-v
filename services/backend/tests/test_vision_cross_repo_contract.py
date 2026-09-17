"""Cross-repository contract test: exercises `VisionRestAdapter` against a
real, running kinetiq-v-vision REST service (not a mock), proving the
adapter's request shapes and response parsing actually match the other
repository's live `/v1/analyses` implementation -- not just the prose in
`contracts/v1/rest-api.md`.

Requires the sibling `kinetiq-v-vision` checkout to be locatable (default:
`../../../kinetiq-v-vision` relative to this file, i.e. a sibling of this
repo's root; override with the `KINETIQ_VISION_REPO_PATH` env var) and `uv`
on PATH to run it. Skipped, not failed, when either is unavailable -- this
is real integration evidence when both repos are checked out side by side
(as in this development environment), not a hard CI dependency on that
layout.

The Vision service under test is wired with an in-memory repository and
stub inference adapters (`Container.create_configured_app()`, see
kinetiq-v-vision `bootstrap/container.py`) -- no database, Redis, or ML
model weights are required, so it starts in well under a second.
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from kinetiq.modules.integrations.vision_adapter import (
    VisionAnalysisNotFoundError,
    VisionClientConfig,
    VisionRestAdapter,
)

_DEFAULT_VISION_REPO = Path(__file__).resolve().parents[4] / "kinetiq-v-vision"
VISION_REPO_PATH = Path(os.environ.get("KINETIQ_VISION_REPO_PATH", _DEFAULT_VISION_REPO))


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _vision_available() -> bool:
    return (
        VISION_REPO_PATH.is_dir()
        and (VISION_REPO_PATH / "pyproject.toml").is_file()
        and shutil.which("uv") is not None
    )


@pytest.fixture(scope="module")
def vision_base_url():
    if not _vision_available():
        pytest.skip(
            f"kinetiq-v-vision checkout not found at {VISION_REPO_PATH} (or 'uv' not on "
            "PATH); set KINETIQ_VISION_REPO_PATH to enable this cross-repo contract test"
        )

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = subprocess.Popen(
        ["uv", "run", "kinetiq-vision", "run", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(VISION_REPO_PATH),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        import urllib.error
        import urllib.request

        deadline = time.monotonic() + 30.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                pytest.fail(
                    f"kinetiq-v-vision process exited early (code {proc.returncode}):\n{output}"
                )
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        break
            except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
                last_error = err
                time.sleep(0.3)
        else:
            proc.terminate()
            raise RuntimeError(
                f"kinetiq-v-vision did not become healthy within 30s: {last_error}"
            )

        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)


@pytest.fixture()
def adapter(vision_base_url: str) -> VisionRestAdapter:
    return VisionRestAdapter(
        config=VisionClientConfig(base_url=vision_base_url, timeout_seconds=5.0)
    )


def test_full_analysis_lifecycle_against_real_vision_service(adapter: VisionRestAdapter) -> None:
    """Create -> status -> candidates -> observations -> delete, all
    against the real running service, asserting on real response shapes."""
    session_id = uuid4()

    created = adapter.create_analysis(
        session_id=session_id,
        source_id="cross-repo-contract-test-camera",
        exercise_key="bodyweight_squat",
        exercise_version=1,
        idempotency_key=f"contract-test-{session_id}",
    )
    assert created.analysis_id
    assert created.epoch == 1
    assert created.state == "AWAITING_SELECTION"
    assert created.session_id == str(session_id)

    status = adapter.get_analysis_status(analysis_id=created.analysis_id)
    assert status.analysis_id == created.analysis_id
    assert status.session_id == str(session_id)
    assert status.epoch == 1
    assert status.state == "AWAITING_SELECTION"

    # No frames have been fed to this analysis (the REST contract does not
    # expose a way to do that -- tracking is not yet wired to a live
    # endpoint per VV-401), so candidates are genuinely empty. This is real
    # evidence the route and response shape (`{"candidates": [...]}`) match
    # what the adapter expects, not evidence of candidate-detection logic.
    candidates = adapter.list_candidates(analysis_id=created.analysis_id)
    assert candidates == ()

    page = adapter.poll_observations(analysis_id=created.analysis_id, limit=10)
    assert page.observations == ()
    assert page.has_more is False

    adapter.delete_analysis(analysis_id=created.analysis_id)

    # DELETE is an idempotent *stop*, not a removal: kinetiq-v-vision's
    # StopAnalysisUseCase transitions the analysis to STOPPED in place
    # (domain/entities.py Analysis.stop()) rather than deleting the record,
    # so it remains fetchable afterward. This is real, verified behavior of
    # the running service, not an assumption -- confirmed by reading
    # StopAnalysisUseCase directly after this test first (correctly)
    # caught a wrong assumption that DELETE would 404 on the next GET.
    status_after_delete = adapter.get_analysis_status(analysis_id=created.analysis_id)
    assert status_after_delete.state == "STOPPED"

    # DELETE is itself idempotent: calling it again on an already-stopped
    # analysis must not error.
    adapter.delete_analysis(analysis_id=created.analysis_id)


def test_get_analysis_status_404_on_real_service(adapter: VisionRestAdapter) -> None:
    """Exercises the adapter's real 404 -> VisionAnalysisNotFoundError
    mapping against the live service's actual error envelope (a
    genuinely-nonexistent analysis_id, not a deleted one -- DELETE does
    not make an analysis 404, see the lifecycle test above)."""
    with pytest.raises(VisionAnalysisNotFoundError):
        adapter.get_analysis_status(analysis_id=f"never-existed-{uuid4()}")


@pytest.mark.xfail(
    reason=(
        "Real defect confirmed against the live service, not a test bug: "
        "kinetiq-v-vision's CreateAnalysisUseCase.execute() "
        "(application/use_cases/create_analysis.py) accepts "
        "command.idempotency_key but never uses it -- every call creates a "
        "new Analysis with a fresh analysis_id regardless of a repeated "
        "key, contradicting contracts/v1/rest-api.md's own documented "
        "contract ('Idempotent on key'). Disclosed, not fixed, in this "
        "pass (out of scope for the kinetiq-v Block 4 review this test was "
        "added for); tracked as a new kinetiq-v-vision defect."
    ),
    strict=True,
)
def test_create_analysis_is_idempotent_on_key_against_real_service(
    adapter: VisionRestAdapter,
) -> None:
    session_id = uuid4()
    idempotency_key = f"contract-idem-{session_id}"

    first = adapter.create_analysis(
        session_id=session_id,
        source_id="cross-repo-contract-test-camera",
        exercise_key="push_up",
        exercise_version=1,
        idempotency_key=idempotency_key,
    )
    second = adapter.create_analysis(
        session_id=session_id,
        source_id="cross-repo-contract-test-camera",
        exercise_key="push_up",
        exercise_version=1,
        idempotency_key=idempotency_key,
    )

    assert first.analysis_id == second.analysis_id
