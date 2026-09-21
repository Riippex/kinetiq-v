from datetime import UTC, datetime
from uuid import uuid4

import pytest

from kinetiq.modules.media.domain.entities import (
    ALLOWED_MEDIA_TYPES,
    MAX_PHOTO_BYTE_LENGTH,
    InvalidPhotoStateError,
    MediaPayloadTooLargeError,
    ProgressPhoto,
    ProgressPhotoStatus,
    UnsupportedMediaTypeError,
)


def test_progress_photo_creation_valid() -> None:
    photo_id = uuid4()
    owner_id = uuid4()
    session_id = uuid4()
    now = datetime.now(UTC)

    photo = ProgressPhoto(
        id=photo_id,
        owner_id=owner_id,
        session_id=session_id,
        s3_key=f"photos/{owner_id}/{photo_id}.jpg",
        content_type="image/jpeg",
        byte_length=1024,
        status=ProgressPhotoStatus.PENDING_UPLOAD,
        created_at=now,
    )

    assert photo.id == photo_id
    assert photo.owner_id == owner_id
    assert photo.session_id == session_id
    assert photo.content_type == "image/jpeg"
    assert photo.status == ProgressPhotoStatus.PENDING_UPLOAD
    assert photo.confirmed_at is None
    assert photo.deleted_at is None


def test_all_allowed_media_types_accepted() -> None:
    now = datetime.now(UTC)
    for ctype in ALLOWED_MEDIA_TYPES:
        photo = ProgressPhoto(
            id=uuid4(),
            owner_id=uuid4(),
            session_id=None,
            s3_key="photos/test.img",
            content_type=ctype,
            byte_length=500,
            status=ProgressPhotoStatus.PENDING_UPLOAD,
            created_at=now,
        )
        assert photo.content_type == ctype


def test_unsupported_media_type_rejected() -> None:
    with pytest.raises(UnsupportedMediaTypeError, match="Unsupported media type 'application/pdf'"):
        ProgressPhoto(
            id=uuid4(),
            owner_id=uuid4(),
            session_id=None,
            s3_key="photos/test.pdf",
            content_type="application/pdf",
            byte_length=500,
            status=ProgressPhotoStatus.PENDING_UPLOAD,
            created_at=datetime.now(UTC),
        )


def test_payload_too_large_rejected() -> None:
    with pytest.raises(MediaPayloadTooLargeError, match="exceeds limit"):
        ProgressPhoto(
            id=uuid4(),
            owner_id=uuid4(),
            session_id=None,
            s3_key="photos/test.jpg",
            content_type="image/jpeg",
            byte_length=MAX_PHOTO_BYTE_LENGTH + 1,
            status=ProgressPhotoStatus.PENDING_UPLOAD,
            created_at=datetime.now(UTC),
        )


def test_zero_or_negative_byte_length_rejected() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        ProgressPhoto(
            id=uuid4(),
            owner_id=uuid4(),
            session_id=None,
            s3_key="photos/test.jpg",
            content_type="image/jpeg",
            byte_length=0,
            status=ProgressPhotoStatus.PENDING_UPLOAD,
            created_at=datetime.now(UTC),
        )


def test_empty_s3_key_rejected() -> None:
    with pytest.raises(ValueError, match="s3_key cannot be empty"):
        ProgressPhoto(
            id=uuid4(),
            owner_id=uuid4(),
            session_id=None,
            s3_key="  ",
            content_type="image/jpeg",
            byte_length=100,
            status=ProgressPhotoStatus.PENDING_UPLOAD,
            created_at=datetime.now(UTC),
        )


def test_confirm_transitions_status() -> None:
    now = datetime.now(UTC)
    photo = ProgressPhoto(
        id=uuid4(),
        owner_id=uuid4(),
        session_id=None,
        s3_key="photos/test.jpg",
        content_type="image/jpeg",
        byte_length=500,
        status=ProgressPhotoStatus.PENDING_UPLOAD,
        created_at=now,
    )

    confirmed_time = datetime.now(UTC)
    confirmed = photo.confirm(confirmed_time)
    assert confirmed.status == ProgressPhotoStatus.CONFIRMED
    assert confirmed.confirmed_at == confirmed_time


def test_cannot_confirm_deleted_photo() -> None:
    now = datetime.now(UTC)
    photo = ProgressPhoto(
        id=uuid4(),
        owner_id=uuid4(),
        session_id=None,
        s3_key="photos/test.jpg",
        content_type="image/jpeg",
        byte_length=500,
        status=ProgressPhotoStatus.DELETED,
        created_at=now,
        deleted_at=now,
    )

    with pytest.raises(InvalidPhotoStateError, match="Cannot confirm a deleted"):
        photo.confirm(datetime.now(UTC))


def test_mark_deleted_sets_tombstone() -> None:
    now = datetime.now(UTC)
    photo = ProgressPhoto(
        id=uuid4(),
        owner_id=uuid4(),
        session_id=None,
        s3_key="photos/test.jpg",
        content_type="image/jpeg",
        byte_length=500,
        status=ProgressPhotoStatus.CONFIRMED,
        created_at=now,
        confirmed_at=now,
    )

    deleted_time = datetime.now(UTC)
    deleted = photo.mark_deleted(deleted_time)
    assert deleted.status == ProgressPhotoStatus.DELETED
    assert deleted.deleted_at == deleted_time
