"""Cloud storage URL parsing utilities."""

from __future__ import annotations

# Scheme prefix lengths: s3:// = 5, gs:// = 5, az:// = 5
_SCHEME_PREFIX_LENGTHS = {"s3": 5, "gs": 5, "az": 5}


def parse_cloud_url(url: str) -> tuple[str, str]:
    """Parse a cloud storage URL into (bucket, prefix) components.

    Supports s3://, gs://, and az:// URL schemes.

    Args:
        url: Cloud URL like 's3://my-bucket/path/prefix/'

    Returns:
        Tuple of (bucket_name, key_prefix). Prefix includes trailing slash.

    Examples:
        >>> parse_cloud_url("s3://my-bucket/staging/")
        ('my-bucket', 'staging/')
        >>> parse_cloud_url("gs://my-bucket/path/")
        ('my-bucket', 'path/')
        >>> parse_cloud_url("s3://my-bucket/")
        ('my-bucket', '')
    """
    scheme = url.split("://", 1)[0]
    prefix_len = _SCHEME_PREFIX_LENGTHS.get(scheme, len(scheme) + 3)
    path = url[prefix_len:]
    if "/" in path:
        bucket, prefix = path.split("/", 1)
    else:
        bucket = path
        prefix = ""
    return bucket, prefix


def parse_s3_url(s3_url: str) -> tuple[str, str]:
    """Parse an S3 URL into (bucket, prefix) components.

    Args:
        s3_url: S3 URL like 's3://my-bucket/path/prefix/'

    Returns:
        Tuple of (bucket_name, key_prefix). Prefix includes trailing slash.
    """
    return parse_cloud_url(s3_url)


def parse_gcs_url(gcs_url: str) -> tuple[str, str]:
    """Parse a GCS URL into (bucket, prefix) components.

    Args:
        gcs_url: GCS URL like 'gs://my-bucket/path/prefix/'

    Returns:
        Tuple of (bucket_name, key_prefix). Prefix includes trailing slash.
    """
    return parse_cloud_url(gcs_url)
