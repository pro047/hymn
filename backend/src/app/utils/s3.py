import os
from typing import Optional

import boto3  # type: ignore[import-not-found]
from botocore.config import Config  # type: ignore[import-not-found]

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "false").lower() in {"1", "true", "yes"}

session = boto3.session.Session(region_name=AWS_REGION)
config = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"} if S3_FORCE_PATH_STYLE else {},
)

s3_client = session.client(
    "s3",
    endpoint_url=S3_ENDPOINT_URL,
    config=config,
)


def presign_put(key: str, expires: int = 900, content_type: Optional[str] = None) -> str:
    """Generate a presigned PUT URL for clients to upload directly to S3."""
    params = {"Bucket": S3_BUCKET, "Key": key}
    if content_type:
        params["ContentType"] = content_type
    return s3_client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires,
    )


def presign_get(key: str, expires: int = 900) -> str:
    """Generate a presigned GET URL to download the object."""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires,
    )
