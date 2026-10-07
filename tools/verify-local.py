"""Check local readiness and an actual photo upload/copy/download/delete round trip."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from kinetiq.modules.media.infrastructure.storage import S3MediaStorageAdapter

load_dotenv(
    Path(__file__).resolve().parents[1] / ".env.development-local", override=True
)

for url in ("http://127.0.0.1:8000/health/", "http://127.0.0.1:8001/ready"):
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.load(response)
        print(f"Ready: {url}")
        if url.endswith("/ready"):
            print(json.dumps(payload))

with urllib.request.urlopen("http://localhost:3000", timeout=60) as response:
    if response.status != 200:
        raise RuntimeError("Local web did not return 200")
    print("Web ready: http://localhost:3000")

storage = S3MediaStorageAdapter(
    bucket_name="kinetiq-media-local",
    endpoint_url="http://127.0.0.1:9000",
    public_endpoint_url="http://127.0.0.1:9000",
)
source = f"smoke/{uuid4()}/upload.jpg"
destination = source.replace("upload.jpg", "final.jpg")
data = b"local-photo-round-trip"
try:
    url = storage.generate_upload_url(
        s3_key=source, content_type="image/jpeg", byte_length=len(data)
    )
    request = urllib.request.Request(
        url, data=data, method="PUT", headers={"Content-Type": "image/jpeg"}
    )
    with urllib.request.urlopen(request, timeout=15):
        pass
    info = storage.get_object_info(s3_key=source)
    if (
        info is None
        or info.content_length != len(data)
        or info.content_type != "image/jpeg"
    ):
        raise RuntimeError("Local object metadata differs from the upload")
    storage.copy_object(source_s3_key=source, dest_s3_key=destination)
    with urllib.request.urlopen(
        storage.generate_download_url(s3_key=destination), timeout=15
    ) as response:
        if response.read() != data:
            raise RuntimeError("Downloaded bytes differ from the upload")
    print("Local photo upload, metadata, final copy, and signed download passed.")
finally:
    storage.delete_object(s3_key=source)
    storage.delete_object(s3_key=destination)
if (
    storage.get_object_info(s3_key=source) is not None
    or storage.get_object_info(s3_key=destination) is not None
):
    raise RuntimeError("Local smoke objects remain after deletion")
print("Local deletion passed. S3 emulation is not AWS security qualification.")
