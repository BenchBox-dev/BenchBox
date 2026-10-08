from __future__ import annotations

_SCHEME_PREFIX_LENGTHS = {"s3": 5, "gs": 5, "az": 5}


def parse_cloud_url(url: str) -> tuple[str, str]:

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

    return parse_cloud_url(s3_url)


def parse_gcs_url(gcs_url: str) -> tuple[str, str]:

    return parse_cloud_url(gcs_url)
