FROM python:3.14-slim

ARG PYSAIL_VERSION=0.6.2
ARG PYSPARK_CLIENT_VERSION=4.1.1

RUN python3 -m pip install --no-cache-dir \
    "pysail==${PYSAIL_VERSION}" \
    "pyspark-client==${PYSPARK_CLIENT_VERSION}"

ENTRYPOINT ["/usr/local/bin/sail"]
