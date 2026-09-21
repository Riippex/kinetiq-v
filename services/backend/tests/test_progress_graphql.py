from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import PerformedSetRecord, WorkoutSessionRecord

PROGRESS_QUERY = """
query GetProgress($fromDate: DateTime!, $toDate: DateTime!) {
  progress(fromDate: $fromDate, toDate: $toDate) {
    fromDate
    toDate
    consistency {
      totalSessions
      completedCount
      plannedSessions
      consistencyRatio
      currentStreakDays
    }
    performanceProjections {
      exerciseId
      exerciseName
      measuredVolume
      selfReportedVolume
      estimated1RM
      trend
      evidenceSource
    }
    goalProgress {
      goalId
      description
      baseline
      target
      currentValue
      unit
      progressRatio
    }
  }
}
"""


@pytest.fixture
def user_a() -> User:
    return User.objects.create_user(username="progress_athlete_a")


@pytest.mark.django_db
def test_progress_query_unauthenticated_rejected() -> None:
    client = Client()
    now = datetime.now(UTC)
    from_str = (now - timedelta(days=7)).isoformat()
    to_str = now.isoformat()

    resp = client.post(
        "/graphql/",
        {"query": PROGRESS_QUERY, "variables": {"fromDate": from_str, "toDate": to_str}},
        content_type="application/json",
    )
    data = resp.json()
    assert "errors" in data
    assert "AUTHENTICATION_REQUIRED" in data["errors"][0]["message"]


@pytest.mark.django_db
def test_progress_query_authenticated_returns_summary(user_a: User) -> None:
    client = Client()
    client.force_login(user_a)

    r_id = uuid4()
    routine = RoutineRecord.objects.create(
        id=r_id,
        routine_id=r_id,
        owner=user_a,
        title="Test Routine",
        version=1,
        prescription={},
    )

    session = WorkoutSessionRecord.objects.create(
        id=uuid4(),
        owner=user_a,
        routine=routine,
        revision=1,
        state="COMPLETED",
        configuration={},
    )

    PerformedSetRecord.objects.create(
        session=session,
        exercise_id="ex-squat",
        set_order=1,
        repetitions=10,
    )

    now = datetime.now(UTC)
    from_str = (now - timedelta(days=7)).isoformat()
    to_str = now.isoformat()

    resp = client.post(
        "/graphql/",
        {"query": PROGRESS_QUERY, "variables": {"fromDate": from_str, "toDate": to_str}},
        content_type="application/json",
    )
    data = resp.json()
    assert "errors" not in data, f"Unexpected GraphQL errors: {data.get('errors')}"
    prog = data["data"]["progress"]
    assert prog["consistency"]["completedCount"] == 1
    assert len(prog["performanceProjections"]) == 1
    proj = prog["performanceProjections"][0]
    assert proj["exerciseId"] == "ex-squat"
    assert proj["exerciseName"] == "Ex Squat"
    # No load/weight measurement exists in this data model, so a reps-only
    # "1RM" is never fabricated.
    assert proj["estimated1RM"] is None
    assert proj["evidenceSource"] in ["MEASURED", "SELF_REPORTED", "ESTIMATED", "MISSING"]
