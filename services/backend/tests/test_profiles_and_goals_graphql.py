import pytest
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User

ME_QUERY = """
query Me {
  me {
    id
    displayName
    timezone
    experienceLevel
    availabilityDaysPerWeek
    targetSessionMinutes
    availableEquipment
    workoutSpace
    preferences
    exclusions
    limitations
    coachingTone
  }
}
"""

UPDATE_PROFILE_MUTATION = """
mutation UpdateProfile($input: UpdateProfileInput!) {
  updateProfile(input: $input) {
    profile {
      id
      displayName
      experienceLevel
      availabilityDaysPerWeek
      targetSessionMinutes
      availableEquipment
      exclusions
    }
    errors {
      code
      message
      field
    }
  }
}
"""

SET_GOAL_MUTATION = """
mutation SetGoal($input: SetGoalInput!) {
  setGoal(input: $input) {
    goal {
      id
      revision
      description
      measure
      baseline
      target
      unit
    }
    errors {
      code
      message
      field
    }
  }
}
"""

GOALS_QUERY = """
query Goals {
  goals {
    id
    revision
    description
    measure
    baseline
    target
    unit
  }
  activeGoal {
    id
    revision
    description
    target
  }
}
"""


@pytest.fixture
def user_a() -> User:
    return User.objects.create_user(username="athlete_a")


@pytest.fixture
def user_b() -> User:
    return User.objects.create_user(username="athlete_b")


@pytest.mark.django_db
def test_unauthenticated_requests_are_rejected() -> None:
    client = Client()

    # 1. me query
    resp = client.post("/graphql/", {"query": ME_QUERY}, content_type="application/json")
    data = resp.json()
    assert "errors" in data
    assert "AUTHENTICATION_REQUIRED" in data["errors"][0]["message"]

    # 2. goals query
    resp = client.post("/graphql/", {"query": GOALS_QUERY}, content_type="application/json")
    data = resp.json()
    assert "errors" in data
    assert "AUTHENTICATION_REQUIRED" in data["errors"][0]["message"]

    # 3. updateProfile mutation
    resp = client.post(
        "/graphql/",
        {"query": UPDATE_PROFILE_MUTATION, "variables": {"input": {"displayName": "Hacker"}}},
        content_type="application/json",
    )
    result = resp.json()["data"]["updateProfile"]
    assert result["profile"] is None
    assert result["errors"][0]["code"] == "AUTHENTICATION_REQUIRED"

    # 4. setGoal mutation
    resp = client.post(
        "/graphql/",
        {"query": SET_GOAL_MUTATION, "variables": {"input": {"description": "Goal"}}},
        content_type="application/json",
    )
    result = resp.json()["data"]["setGoal"]
    assert result["goal"] is None
    assert result["errors"][0]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.django_db
def test_authenticated_user_can_query_and_update_profile(user_a: User) -> None:
    client = Client()
    client.force_login(user_a)

    # 1. Initial me query auto-populates defaults
    resp = client.post("/graphql/", {"query": ME_QUERY}, content_type="application/json")
    data = resp.json()["data"]["me"]
    assert data["id"] == str(user_a.pk)
    assert data["experienceLevel"] == "RETURNING"
    assert data["availabilityDaysPerWeek"] == 3

    # 2. Update profile
    update_vars = {
        "input": {
            "displayName": "Alex Athlete",
            "experienceLevel": "REGULAR",
            "availabilityDaysPerWeek": 4,
            "targetSessionMinutes": 20,
            "availableEquipment": ["NONE", "MAT"],
            "exclusions": ["exercise-burpee-v1"],
        }
    }
    resp = client.post(
        "/graphql/",
        {"query": UPDATE_PROFILE_MUTATION, "variables": update_vars},
        content_type="application/json",
    )
    update_data = resp.json()["data"]["updateProfile"]
    assert update_data["errors"] == []
    profile = update_data["profile"]
    assert profile["displayName"] == "Alex Athlete"
    assert profile["experienceLevel"] == "REGULAR"
    assert profile["availabilityDaysPerWeek"] == 4
    assert profile["targetSessionMinutes"] == 20
    assert profile["availableEquipment"] == ["NONE", "MAT"]
    assert profile["exclusions"] == ["exercise-burpee-v1"]


@pytest.mark.django_db
def test_authenticated_user_can_set_and_revise_goals_preserving_history(user_a: User) -> None:
    client = Client()
    client.force_login(user_a)

    # 1. Initial goal (revision 1)
    vars1 = {
        "input": {
            "description": "Establish routine consistency",
            "measure": "weekly_completed_sessions",
            "baseline": 0.0,
            "target": 3.0,
            "unit": "sessions/week",
        }
    }
    resp1 = client.post(
        "/graphql/",
        {"query": SET_GOAL_MUTATION, "variables": vars1},
        content_type="application/json",
    )
    res1 = resp1.json()["data"]["setGoal"]
    assert res1["errors"] == []
    goal1 = res1["goal"]
    assert goal1["revision"] == 1
    assert goal1["description"] == "Establish routine consistency"
    assert goal1["target"] == 3.0
    goal_id = goal1["id"]

    # 2. Revised goal (revision 2)
    vars2 = {
        "input": {
            "description": "Progress to 4 weekly sessions",
            "measure": "weekly_completed_sessions",
            "baseline": 3.0,
            "target": 4.0,
            "unit": "sessions/week",
        }
    }
    resp2 = client.post(
        "/graphql/",
        {"query": SET_GOAL_MUTATION, "variables": vars2},
        content_type="application/json",
    )
    res2 = resp2.json()["data"]["setGoal"]
    assert res2["errors"] == []
    goal2 = res2["goal"]
    assert goal2["id"] == goal_id  # Logical goal ID preserved
    assert goal2["revision"] == 2
    assert goal2["target"] == 4.0

    # 3. Query activeGoal and historical goals
    query_resp = client.post("/graphql/", {"query": GOALS_QUERY}, content_type="application/json")
    query_data = query_resp.json()["data"]

    active = query_data["activeGoal"]
    assert active["revision"] == 2
    assert active["target"] == 4.0

    history = query_data["goals"]
    assert len(history) == 2
    assert history[0]["revision"] == 2
    assert history[1]["revision"] == 1


@pytest.mark.django_db
def test_cross_user_isolation(user_a: User, user_b: User) -> None:
    client_a = Client()
    client_a.force_login(user_a)

    # User A updates profile and sets goal
    client_a.post(
        "/graphql/",
        {
            "query": UPDATE_PROFILE_MUTATION,
            "variables": {"input": {"displayName": "User A Private Profile"}},
        },
        content_type="application/json",
    )
    client_a.post(
        "/graphql/",
        {
            "query": SET_GOAL_MUTATION,
            "variables": {"input": {"description": "User A Private Goal", "target": 5.0}},
        },
        content_type="application/json",
    )

    # User B logs in
    client_b = Client()
    client_b.force_login(user_b)

    # User B checks their own profile
    resp_b_me = client_b.post("/graphql/", {"query": ME_QUERY}, content_type="application/json")
    me_b = resp_b_me.json()["data"]["me"]
    assert me_b["id"] == str(user_b.pk)
    assert me_b["displayName"] != "User A Private Profile"

    # User B checks goals: cannot see User A's goals
    resp_b_goals = client_b.post(
        "/graphql/", {"query": GOALS_QUERY}, content_type="application/json"
    )
    goals_b = resp_b_goals.json()["data"]["goals"]
    assert len(goals_b) == 0
    assert resp_b_goals.json()["data"]["activeGoal"] is None
