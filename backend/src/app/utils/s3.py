import os
from urllib.parse import urlparse

import boto3  # type: ignore[import-not-found]
from botocore.config import Config  # type: ignore[import-not-found]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-not-found]

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_PUBLIC_BASE_URL = os.getenv("S3_PUBLIC_BASE_URL")
S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "false").lower() in {"1", "true", "yes"}

session = boto3.session.Session(region_name=AWS_REGION)
# presign_put/presign_get/object_url never hit the network (SigV4 is a local
# computation), so this timeout is a no-op for them. get_object_bytes below is
# the first caller that actually opens a connection, and boto3's own defaults
# (60s connect, 60s read, 5 attempts) would let one slow object hold a sync
# route's anyio worker for minutes — the same reasoning SES timeouts followed
# in utils/email.py.
config = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"} if S3_FORCE_PATH_STYLE else {},
    connect_timeout=3,
    read_timeout=10,
    retries={"max_attempts": 2, "mode": "standard"},
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


class ObjectNotReadable(Exception):
    """This key's bytes could not be fetched. The cause (missing/network/permission) is not distinguished."""


class ObjectTooLarge(ObjectNotReadable):
    """The object exists but is over the size this process is willing to hold."""


# presign_put signs a PUT with only Bucket/Key, so nothing on the upload path
# caps an object's size, and the whole object lands in this process's memory.
# Production is a 2 GiB t4g.small running nginx, backend and frontend together
# (infra/main.tf:68). 20 MB is ~16x the largest score in production (1.20 MB;
# 85 songs measured 2026-09-06, median 137 KB), so it bounds a runaway upload
# without coming near real data.
MAX_OBJECT_BYTES = 20 * 1024 * 1024


def get_object_bytes(key: str, max_bytes: int = MAX_OBJECT_BYTES) -> bytes:
    """Read an object's full bytes, or raise ObjectNotReadable.

    The only caller today (conti PDF generation) treats every failure mode
    the same way, so the underlying botocore error is kept only as __cause__
    for logging rather than surfaced as a distinct exception type.

    An object larger than max_bytes is refused from the GetObject response
    metadata before its body is read, so an oversized object costs one round
    trip rather than its own size in RAM.
    """
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
    except (ClientError, BotoCoreError) as exc:
        raise ObjectNotReadable(key) from exc

    body = response["Body"]
    size = response.get("ContentLength")
    # A missing ContentLength is refused rather than read: the point of the
    # cap is that nothing unbounded reaches memory, and "the server did not
    # say how big it is" is not a reason to trust it.
    if size is None or size > max_bytes:
        # close() returns the pooled urllib3 connection. Without it the pool
        # (10 by default) only frees on GC, so repeated oversized reads stall
        # later S3 calls waiting for a slot.
        body.close()
        raise ObjectTooLarge(f"{key}: {size} bytes against a {max_bytes} byte limit")
    try:
        return body.read()
    except (ClientError, BotoCoreError) as exc:
        raise ObjectNotReadable(key) from exc
    finally:
        body.close()


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
