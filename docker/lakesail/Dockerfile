FROM python:3.14-slim

ARG PYSAIL_VERSION=0.7.1
ARG PYSPARK_CLIENT_VERSION=4.2.0

# pyspark-client >=4.2.0 hard-exits at import time if SPARK_HOME is unset
# (it no longer tolerates a bundle-less, Connect-only install); any nonexistent
# path satisfies pyspark's find_spark_home() check since it trusts the env var
# without validating its contents.
ENV SPARK_HOME=/opt/pyspark-client-no-spark-home

RUN python3 -m pip install --no-cache-dir \
    "pysail==${PYSAIL_VERSION}" \
    "pyspark-client==${PYSPARK_CLIENT_VERSION}"

ENTRYPOINT ["/usr/local/bin/sail"]
