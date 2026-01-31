import os
from typing import Optional
from urllib.parse import urlparse

import boto3  # type: ignore[import-not-found]
from botocore.config import Config  # type: ignore[import-not-found]

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_PUBLIC_BASE_URL = os.getenv("S3_PUBLIC_BASE_URL")
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


def presign_put(key: str, expires: int = 900) -> str:
    """Generate a presigned PUT URL for clients to upload directly to S3."""
    params = {"Bucket": S3_BUCKET, "Key": key}
    url = s3_client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires,
    )
    return url


def presign_get(key: str, expires: int = 900) -> str:
    """Generate a presigned GET URL to download the object."""
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires,
    )
    return rewrite_presigned_url(url)


def object_url(key: str) -> str:
    """Build a stable object URL for the given key."""
    if not S3_BUCKET:
        raise RuntimeError("S3_BUCKET is required to build object URL")
    if S3_PUBLIC_BASE_URL:
        base = S3_PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/{S3_BUCKET}/{key}"
    if S3_ENDPOINT_URL:
        endpoint = S3_ENDPOINT_URL.rstrip("/")
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        is_local = host in {"localhost", "127.0.0.1"} or host.endswith(".localhost")
        if S3_FORCE_PATH_STYLE or is_local:
            return f"{endpoint}/{S3_BUCKET}/{key}"
        if parsed.scheme and parsed.netloc:
            base = f"{parsed.scheme}://{S3_BUCKET}.{parsed.netloc}{parsed.path.rstrip('/')}"
            return f"{base}/{key}"
        return f"{endpoint}/{key}"
    if AWS_REGION == "us-east-1":
        return f"https://{S3_BUCKET}.s3.amazonaws.com/{key}"
    return f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{key}"


def rewrite_presigned_url(url: str) -> str:
    """Rewrite presigned URL host for clients when a public base is provided."""
    if not S3_PUBLIC_BASE_URL:
        return url
    base = urlparse(S3_PUBLIC_BASE_URL.rstrip("/"))
    target = urlparse(url)
    if not base.scheme or not base.netloc:
        return url
    base_path = base.path.rstrip("/")
    path = target.path
    if base_path:
        path = f"{base_path}{path}"
    return target._replace(scheme=base.scheme, netloc=base.netloc, path=path).geturl()
