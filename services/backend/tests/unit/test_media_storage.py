from unittest.mock import MagicMock

from kinetiq.modules.media.infrastructure.storage import (
    InMemoryMediaStorageAdapter,
    S3MediaStorageAdapter,
)


def test_in_memory_storage_adapter() -> None:
    storage = InMemoryMediaStorageAdapter(bucket_name="test-bucket")

    upload_url = storage.generate_upload_url(
        s3_key="photos/u1/p1.jpg", content_type="image/jpeg", ttl_seconds=300
    )
    assert "https://mock-s3.local/test-bucket/photos/u1/p1.jpg" in upload_url
    assert "action=put" in upload_url
    assert "ttl=300" in upload_url

    download_url = storage.generate_download_url(s3_key="photos/u1/p1.jpg", ttl_seconds=600)
    assert "https://mock-s3.local/test-bucket/photos/u1/p1.jpg" in download_url
    assert "action=get" in download_url
    assert "ttl=600" in download_url

    # Object does not exist initially
    assert not storage.object_exists(s3_key="photos/u1/p1.jpg")

    # Put object
    storage.put_object_data(s3_key="photos/u1/p1.jpg", data=b"binary-jpeg-data")
    assert storage.object_exists(s3_key="photos/u1/p1.jpg")

    # Delete object
    storage.delete_object(s3_key="photos/u1/p1.jpg")
    assert not storage.object_exists(s3_key="photos/u1/p1.jpg")


def test_s3_storage_adapter_generates_presigned_urls() -> None:
    adapter = S3MediaStorageAdapter(bucket_name="my-bucket", region="eu-west-1")

    mock_client = MagicMock()
    mock_client.generate_presigned_url.side_effect = lambda op, Params, ExpiresIn: (
        f"https://s3.eu-west-1.amazonaws.com/{Params['Bucket']}/{Params['Key']}?op={op}&ttl={ExpiresIn}"
    )
    adapter._client = mock_client

    upload_url = adapter.generate_upload_url(
        s3_key="photos/user/1.png", content_type="image/png", ttl_seconds=450
    )
    expected_upload = (
        "https://s3.eu-west-1.amazonaws.com/my-bucket/photos/user/1.png?op=put_object&ttl=450"
    )
    assert upload_url == expected_upload
    mock_client.generate_presigned_url.assert_called_with(
        "put_object",
        Params={"Bucket": "my-bucket", "Key": "photos/user/1.png", "ContentType": "image/png"},
        ExpiresIn=450,
    )

    download_url = adapter.generate_download_url(s3_key="photos/user/1.png", ttl_seconds=450)
    expected_download = (
        "https://s3.eu-west-1.amazonaws.com/my-bucket/photos/user/1.png?op=get_object&ttl=450"
    )
    assert download_url == expected_download


def test_s3_storage_adapter_object_exists_and_delete() -> None:
    adapter = S3MediaStorageAdapter(bucket_name="my-bucket")
    mock_client = MagicMock()
    adapter._client = mock_client

    # Object exists
    assert adapter.object_exists(s3_key="photos/user/1.png") is True
    mock_client.head_object.assert_called_with(Bucket="my-bucket", Key="photos/user/1.png")

    # Object delete
    adapter.delete_object(s3_key="photos/user/1.png")
    mock_client.delete_object.assert_called_with(Bucket="my-bucket", Key="photos/user/1.png")
