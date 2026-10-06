"""Object storage: Cloudflare R2 when configured, a local directory otherwise.

Keys look like `lectures/<id>/parts/0-recording.m4a`. All methods are synchronous (boto3);
async code calls them through `asyncio.to_thread`.
"""

import mimetypes
import shutil
from functools import cache
from pathlib import Path

import boto3
from botocore.config import Config

from app.config import settings


@cache
def _s3():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _local(key: str) -> Path:
    path = (Path(settings.storage_dir) / key).resolve()
    if not path.is_relative_to(Path(settings.storage_dir).resolve()):
        raise ValueError("key escapes the storage directory")
    return path


def put_file(key: str, path: Path, content_type: str | None = None) -> None:
    content_type = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    if settings.r2_configured:
        _s3().upload_file(str(path), settings.r2_bucket_name, key, ExtraArgs={"ContentType": content_type})
        return
    dest = _local(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)


def put_bytes(key: str, data: bytes, content_type: str | None = None) -> None:
    content_type = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    if settings.r2_configured:
        _s3().put_object(Bucket=settings.r2_bucket_name, Key=key, Body=data, ContentType=content_type)
        return
    dest = _local(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def get_to_path(key: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if settings.r2_configured:
        _s3().download_file(settings.r2_bucket_name, key, str(path))
        return
    shutil.copyfile(_local(key), path)


def get_bytes(key: str) -> bytes:
    if settings.r2_configured:
        return _s3().get_object(Bucket=settings.r2_bucket_name, Key=key)["Body"].read()
    return _local(key).read_bytes()


def exists(key: str) -> bool:
    if settings.r2_configured:
        try:
            _s3().head_object(Bucket=settings.r2_bucket_name, Key=key)
            return True
        except _s3().exceptions.ClientError:
            return False
    return _local(key).exists()


def delete_prefix(prefix: str) -> None:
    if settings.r2_configured:
        paginator = _s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.r2_bucket_name, Prefix=prefix):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                _s3().delete_objects(Bucket=settings.r2_bucket_name, Delete={"Objects": keys})
        return
    shutil.rmtree(_local(prefix), ignore_errors=True)


def presigned_url(key: str, expires: int = 3600) -> str | None:
    """A time-limited direct URL (R2), or None when files are local and must be streamed by the app."""
    if not settings.r2_configured:
        return None
    return _s3().generate_presigned_url(
        "get_object", Params={"Bucket": settings.r2_bucket_name, "Key": key}, ExpiresIn=expires
    )


def local_path(key: str) -> Path:
    return _local(key)
