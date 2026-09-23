from uuid import uuid4

import pytest
from django.test import Client

from kinetiq.bootstrap.container import get_media_storage
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.media.infrastructure.models import ProgressPhotoRecord
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord

REQUEST_UPLOAD_MUTATION = """
mutation RequestUpload(
  $contentType: String!
  $byteLength: Int!
  $idempotencyKey: String!
  $sessionId: ID
) {
  requestProgressPhotoUpload(
    contentType: $contentType
    byteLength: $byteLength
    idempotencyKey: $idempotencyKey
    sessionId: $sessionId
  ) {
    uploadRequest {
      photoId
      uploadUrl
      expiresAt
    }
    errors {
      code
      message
      field
    }
  }
}
"""

FINALIZE_PHOTO_MUTATION = """
mutation FinalizePhoto($photoId: ID!) {
  finalizeProgressPhoto(photoId: $photoId) {
    photo {
      id
      sessionId
      contentType
      byteLength
      url
      status
      createdAt
      confirmedAt
    }
    errors {
      code
      message
      field
    }
  }
}
"""

PROGRESS_PHOTOS_QUERY = """
query GetPhotos($sessionId: ID) {
  progressPhotos(sessionId: $sessionId) {
    id
    sessionId
    contentType
    byteLength
    url
    status
    createdAt
    confirmedAt
  }
}
"""

DELETE_PHOTO_MUTATION = """
mutation DeletePhoto($photoId: ID!) {
  deleteProgressPhoto(photoId: $photoId) {
    success
    storageCleanup
    errors {
      code
      message
      field
    }
  }
}
"""

FINISH_SESSION_MUTATION = """
mutation FinishSession($command: SessionCommandInput!, $performedSets: [PerformedSetInput!]) {
  finishSession(command: $command, performedSets: $performedSets) {
    session {
      id
      state
      confirmedRepetitions
      performedSets {
        exerciseId
        repetitions
      }
    }
    errors {
      code
      message
    }
  }
}
"""


def _post_graphql(client: Client, query: str, variables: dict | None = None) -> dict:
    resp = client.post(
        "/graphql/",
        data={"query": query, "variables": variables or {}},
        content_type="application/json",
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.django_db
def test_media_graphql_requires_authentication() -> None:
    client = Client()

    # 1. requestProgressPhotoUpload
    res = _post_graphql(
        client,
        REQUEST_UPLOAD_MUTATION,
        {
            "contentType": "image/jpeg",
            "byteLength": 1024,
            "idempotencyKey": "key-anon",
        },
    )
    errors = res["data"]["requestProgressPhotoUpload"]["errors"]
    assert any(e["code"] == "AUTHENTICATION_REQUIRED" for e in errors)

    # 2. finalizeProgressPhoto
    res = _post_graphql(client, FINALIZE_PHOTO_MUTATION, {"photoId": str(uuid4())})
    errors = res["data"]["finalizeProgressPhoto"]["errors"]
    assert any(e["code"] == "AUTHENTICATION_REQUIRED" for e in errors)

    # 3. deleteProgressPhoto
    res = _post_graphql(client, DELETE_PHOTO_MUTATION, {"photoId": str(uuid4())})
    errors = res["data"]["deleteProgressPhoto"]["errors"]
    assert any(e["code"] == "AUTHENTICATION_REQUIRED" for e in errors)

    # 4. progressPhotos query
    res = _post_graphql(client, PROGRESS_PHOTOS_QUERY)
    assert "errors" in res
    assert "AUTHENTICATION_REQUIRED" in res["errors"][0]["message"]


@pytest.mark.django_db
def test_media_graphql_full_lifecycle() -> None:
    user = User.objects.create_user(username="media-athlete", password="password123")
    client = Client()
    client.force_login(user)

    # 1. Request photo upload
    res = _post_graphql(
        client,
        REQUEST_UPLOAD_MUTATION,
        {
            "contentType": "image/jpeg",
            "byteLength": 2048,
            "idempotencyKey": "photo-idem-1",
        },
    )
    upload_data = res["data"]["requestProgressPhotoUpload"]
    assert len(upload_data["errors"]) == 0
    photo_id = upload_data["uploadRequest"]["photoId"]
    upload_url = upload_data["uploadRequest"]["uploadUrl"]
    assert "photos/" in upload_url

    # 2. Attempt to finalize before upload -> fails with UPLOAD_NOT_COMPLETED
    fin_fail = _post_graphql(client, FINALIZE_PHOTO_MUTATION, {"photoId": photo_id})
    assert fin_fail["data"]["finalizeProgressPhoto"]["photo"] is None
    assert any(
        e["code"] == "UPLOAD_NOT_COMPLETED"
        for e in fin_fail["data"]["finalizeProgressPhoto"]["errors"]
    )

    # 3. Simulate S3 upload
    storage = get_media_storage()
    record = ProgressPhotoRecord.objects.get(id=photo_id)
    if hasattr(storage, "put_object_data"):
        storage.put_object_data(s3_key=record.s3_key, data=b"x" * 2048, content_type="image/jpeg")

    # 4. Finalize after upload -> succeeds
    fin_ok = _post_graphql(client, FINALIZE_PHOTO_MUTATION, {"photoId": photo_id})
    photo_data = fin_ok["data"]["finalizeProgressPhoto"]["photo"]
    assert photo_data["id"] == photo_id
    assert photo_data["status"] == "CONFIRMED"
    assert photo_data["confirmedAt"] is not None
    # Seventh Codex adversarial-review pass, finding #1: downloads are served
    # from the immutable key finalize copied the validated object to, never
    # from the mutable staging key a stale presigned PUT could still target.
    assert "photos-confirmed/" in photo_data["url"]

    # 5. Query progress photos
    query_res = _post_graphql(client, PROGRESS_PHOTOS_QUERY)
    photos = query_res["data"]["progressPhotos"]
    assert len(photos) == 1
    assert photos[0]["id"] == photo_id

    # 6. Delete progress photo
    del_res = _post_graphql(client, DELETE_PHOTO_MUTATION, {"photoId": photo_id})
    assert del_res["data"]["deleteProgressPhoto"]["success"] is True
    # The object is removed immediately, but the presigned upload URL from
    # step 1 is still within its authorization window, so cleanup is
    # reported PENDING (not COMPLETED) until that window elapses -- see
    # test_media_persistence.py for the full deferred-verification flow.
    assert del_res["data"]["deleteProgressPhoto"]["storageCleanup"] == "PENDING"
    assert not storage.has_object(s3_key=record.s3_key)

    # 7. Query progress photos after deletion -> empty
    query_after = _post_graphql(client, PROGRESS_PHOTOS_QUERY)
    assert len(query_after["data"]["progressPhotos"]) == 0


@pytest.mark.django_db
def test_media_graphql_cross_user_isolation() -> None:
    user_a = User.objects.create_user(username="user-a", password="password")
    user_b = User.objects.create_user(username="user-b", password="password")

    client_a = Client()
    client_a.force_login(user_a)

    client_b = Client()
    client_b.force_login(user_b)

    # User A requests and confirms a photo
    res_a = _post_graphql(
        client_a,
        REQUEST_UPLOAD_MUTATION,
        {
            "contentType": "image/png",
            "byteLength": 1024,
            "idempotencyKey": "user-a-key",
        },
    )
    photo_id = res_a["data"]["requestProgressPhotoUpload"]["uploadRequest"]["photoId"]
    record = ProgressPhotoRecord.objects.get(id=photo_id)
    storage = get_media_storage()
    if hasattr(storage, "put_object_data"):
        storage.put_object_data(s3_key=record.s3_key, data=b"x" * 1024, content_type="image/png")

    _post_graphql(client_a, FINALIZE_PHOTO_MUTATION, {"photoId": photo_id})

    # User B lists photos -> empty list
    photos_b = _post_graphql(client_b, PROGRESS_PHOTOS_QUERY)["data"]["progressPhotos"]
    assert len(photos_b) == 0

    # User B attempts to delete User A's photo -> PHOTO_NOT_FOUND error
    del_b = _post_graphql(client_b, DELETE_PHOTO_MUTATION, {"photoId": photo_id})
    assert del_b["data"]["deleteProgressPhoto"]["success"] is False
    assert any(
        e["code"] == "PHOTO_NOT_FOUND" for e in del_b["data"]["deleteProgressPhoto"]["errors"]
    )


@pytest.mark.django_db
def test_photo_failure_cannot_undo_or_affect_workout_session() -> None:
    """Core acceptance test for KV-601: Photo failure cannot undo a workout."""
    athlete = User.objects.create_user(username="athlete-workout", password="password")
    client = Client()
    client.force_login(athlete)

    # Prepare routine and workout session
    routine_id = uuid4()
    exercise_id = "exercise-push-up-v1"
    routine = RoutineRecord.objects.create(
        owner=athlete,
        routine_id=routine_id,
        version=1,
        title="Workout Test Routine",
        rationale="Testing photo independence",
        prescription={
            "items": [
                {
                    "exerciseId": exercise_id,
                    "name": "Push Up",
                    "order": 1,
                    "sets": 1,
                    "repetitions": 15,
                }
            ]
        },
        accepted=True,
    )

    session_id = uuid4()
    session = WorkoutSessionRecord.objects.create(
        id=session_id,
        owner=athlete,
        routine=routine,
        revision=1,
        state="ACTIVE",
        configuration={
            "requested_mode": "NORMAL",
            "active_mode": "NORMAL",
            "intensity": "PLANNED",
            "coaching_tone": "CALM",
            "capture_device_id": "phone-camera",
            "display_device_id": None,
            "prompt_for_progress_photo": True,
            "dynamic": None,
        },
        confirmed_repetitions=0,
    )

    # 1. Complete the workout session
    finish_res = _post_graphql(
        client,
        FINISH_SESSION_MUTATION,
        {
            "command": {
                "sessionId": str(session.id),
                "expectedRevision": 1,
                "idempotencyKey": "finish-key-1",
            },
            "performedSets": [
                {
                    "exerciseId": exercise_id,
                    "setOrder": 1,
                    "repetitions": 15,
                }
            ],
        },
    )
    finished_data = finish_res["data"]["finishSession"]
    assert len(finished_data["errors"]) == 0
    assert finished_data["session"]["state"] == "COMPLETED"
    assert finished_data["session"]["confirmedRepetitions"] == 15

    # 2. Athlete attempts optional progress photo upload linked to the completed session
    upload_res = _post_graphql(
        client,
        REQUEST_UPLOAD_MUTATION,
        {
            "contentType": "image/jpeg",
            "byteLength": 4096,
            "idempotencyKey": "photo-upload-key",
            "sessionId": str(session.id),
        },
    )
    photo_id = upload_res["data"]["requestProgressPhotoUpload"]["uploadRequest"]["photoId"]

    # 3. Simulate photo failure: network drops, upload is aborted or S3 reject
    # Attempting to finalize fails because file was never uploaded
    fin_fail = _post_graphql(client, FINALIZE_PHOTO_MUTATION, {"photoId": photo_id})
    assert fin_fail["data"]["finalizeProgressPhoto"]["photo"] is None
    assert any(
        e["code"] == "UPLOAD_NOT_COMPLETED"
        for e in fin_fail["data"]["finalizeProgressPhoto"]["errors"]
    )

    # 4. Verify workout session remains completely INTACT and COMPLETED!
    session.refresh_from_db()
    assert session.state == "COMPLETED"
    assert session.confirmed_repetitions == 15
    assert session.performed_sets.count() == 1
    assert session.performed_sets.first().repetitions == 15

    # 5. Athlete deletes or abandons the failed photo
    del_res = _post_graphql(client, DELETE_PHOTO_MUTATION, {"photoId": photo_id})
    assert del_res["data"]["deleteProgressPhoto"]["success"] is True

    # 6. Workout session STILL 100% completed and unaffected
    session.refresh_from_db()
    assert session.state == "COMPLETED"
    assert session.confirmed_repetitions == 15
