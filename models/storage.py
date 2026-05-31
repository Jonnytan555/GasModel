"""
models/storage.py — S3-aware model persistence.

If MODELS_DIR starts with s3:// all save/load/list/delete operations go
through boto3.  Otherwise the local filesystem is used unchanged, so local
development and Docker Compose runs need no special config.

S3 path format:  s3://bucket-name/optional/prefix/
"""

import io
import fnmatch
import logging
import joblib
from pathlib import Path


def _is_s3(path) -> bool:
    return str(path).startswith("s3://")


def _parse_s3(path) -> tuple[str, str]:
    """s3://bucket/key/path  →  (bucket, key/path)"""
    without_scheme = str(path)[5:]
    parts = without_scheme.split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def model_exists(path) -> bool:
    if _is_s3(path):
        import boto3
        from botocore.exceptions import ClientError
        bucket, key = _parse_s3(path)
        try:
            boto3.client("s3").head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False
    return Path(path).exists()


def save_model(obj, path) -> None:
    if _is_s3(path):
        import boto3
        bucket, key = _parse_s3(path)
        buf = io.BytesIO()
        joblib.dump(obj, buf)
        buf.seek(0)
        boto3.client("s3").upload_fileobj(buf, bucket, key)
        logging.info("[storage] Saved → s3://%s/%s", bucket, key)
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(obj, path)


def load_model(path):
    if _is_s3(path):
        import boto3
        bucket, key = _parse_s3(path)
        buf = io.BytesIO()
        boto3.client("s3").download_fileobj(bucket, key, buf)
        buf.seek(0)
        return joblib.load(buf)
    return joblib.load(path)


def list_versioned(models_dir, model_name: str) -> list[str]:
    """Return sorted list of versioned .pkl paths for a given model name."""
    pattern = f"{model_name}_????????T??????.pkl"
    if _is_s3(models_dir):
        import boto3
        bucket, prefix = _parse_s3(models_dir)
        resp = boto3.client("s3").list_objects_v2(Bucket=bucket, Prefix=prefix)
        keys = sorted(
            obj["Key"] for obj in resp.get("Contents", [])
            if fnmatch.fnmatch(obj["Key"].split("/")[-1], pattern)
        )
        return [f"s3://{bucket}/{k}" for k in keys]
    return sorted(str(p) for p in Path(models_dir).glob(pattern))


def delete_model(path) -> None:
    if _is_s3(path):
        import boto3
        bucket, key = _parse_s3(path)
        boto3.client("s3").delete_object(Bucket=bucket, Key=key)
        logging.info("[storage] Deleted s3://%s/%s", bucket, key)
    else:
        Path(path).unlink(missing_ok=True)
