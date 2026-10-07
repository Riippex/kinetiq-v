"""Initialize the private local S3 bucket from inside the backend container."""

import os
import time

import boto3
from botocore.exceptions import ClientError

endpoint = os.environ["MEDIA_S3_ENDPOINT_URL"]
client = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1")
for attempt in range(30):
    try:
        client.list_buckets()
        break
    except OSError:
        if attempt == 29:
            raise
        time.sleep(1)

bucket = os.environ["MEDIA_S3_BUCKET"]
try:
    client.head_bucket(Bucket=bucket)
except ClientError as error:
    if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
        raise
    client.create_bucket(Bucket=bucket)
print("Local media bucket ready (S3 emulation; not AWS security evidence).")
