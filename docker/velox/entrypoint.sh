#!/bin/bash
# BenchBox Velox entrypoint
#
# Modes (first argument):
#   connect   - start a Gluten-enabled Spark-Connect server on port 50051 (default)
#   run       - execute `benchbox run` with remaining arguments inside the container
#   shell     - drop into a bash shell (for debugging)
#   <other>   - exec the command directly
#
# Environment variables:
#   GLUTEN_JAR        path to the Gluten bundle jar (default: /opt/gluten.jar)
#   SPARK_DRIVER_MEM  driver heap memory (default: 4g)
#   VELOX_OFFHEAP     off-heap memory for Velox (default: 8g)
#   SPARK_CONNECT_PORT Spark-Connect listen port (default: 50051)

set -euo pipefail

GLUTEN_JAR="${GLUTEN_JAR:-/opt/gluten.jar}"
SPARK_DRIVER_MEM="${SPARK_DRIVER_MEM:-4g}"
VELOX_OFFHEAP="${VELOX_OFFHEAP:-8g}"
SPARK_CONNECT_PORT="${SPARK_CONNECT_PORT:-50051}"

# The apache/spark base image does not export SPARK_VERSION.
# start-connect-server.sh needs it to locate spark-connect_2.13-${SPARK_VERSION}.jar.
# The Dockerfile wrote the detected version to /opt/spark/SPARK_VERSION at build time.
# Fail loud if it's missing - empty SPARK_VERSION makes start-connect-server.sh
# silently skip adding Spark Connect to the classpath, leaving the container
# running but with no gRPC server (a healthcheck-passes-but-connections-fail trap).
if [[ -z "${SPARK_VERSION:-}" ]]; then
    if [[ -r /opt/spark/SPARK_VERSION ]]; then
        SPARK_VERSION="$(cat /opt/spark/SPARK_VERSION)"
    else
        echo "FATAL: SPARK_VERSION is unset and /opt/spark/SPARK_VERSION is not readable." >&2
        echo "       The Dockerfile is expected to write this file at build time." >&2
        exit 1
    fi
fi
if [[ -z "${SPARK_VERSION}" ]]; then
    echo "FATAL: SPARK_VERSION resolved to an empty string." >&2
    exit 1
fi
export SPARK_VERSION

# Shared Spark configuration for Gluten + Velox
GLUTEN_CONF=(
    "--conf" "spark.plugins=org.apache.gluten.GlutenPlugin"
    "--conf" "spark.memory.offHeap.enabled=true"
    "--conf" "spark.memory.offHeap.size=${VELOX_OFFHEAP}"
    "--conf" "spark.shuffle.manager=org.apache.spark.shuffle.sort.ColumnarShuffleManager"
    "--conf" "spark.driver.extraClassPath=${GLUTEN_JAR}"
    "--conf" "spark.executor.extraClassPath=${GLUTEN_JAR}"
    "--conf" "spark.driver.memory=${SPARK_DRIVER_MEM}"
    "--conf" "spark.sql.adaptive.enabled=true"
    # Register BenchBox's zstd-jni-backed Hadoop codec so Spark can read .zst
    # files.  The official apache/spark image's libhadoop was built without
    # native zstd support, so Hadoop's ZStandardCodec always fails.  This
    # codec wraps ZstdInputStream from the zstd-jni jar already on the
    # classpath and is compiled into benchbox-zstd-codec.jar by the Dockerfile.
    "--conf" "spark.hadoop.io.compression.codecs=io.benchbox.codec.ZstdJniCodec"
    # Use /tmp for managed table warehouse.  /tmp is mounted as tmpfs in
    # docker/velox/docker-compose.yml, so the warehouse is truly ephemeral
    # across both `docker stop`/`docker start` and `docker compose down/up`.
    # Without the tmpfs mount, /tmp is part of the container's writable layer
    # and survives stop/start - a restarted container would still lose the
    # in-memory Derby metastore but retain spark-warehouse, causing
    # LOCATION_ALREADY_EXISTS on the next CREATE TABLE for any previously-
    # loaded benchmark.  The Velox adapter's purge_orphaned_warehouse_directory
    # is the in-process safety net for any path that bypasses the tmpfs.
    "--conf" "spark.sql.warehouse.dir=/tmp/spark-warehouse"
)

MODE="${1:-connect}"

case "${MODE}" in
  connect)
    echo "[velox-entrypoint] Starting Gluten-enabled Spark-Connect server on port ${SPARK_CONNECT_PORT}"
    echo "[velox-entrypoint] Gluten jar: ${GLUTEN_JAR}"
    echo "[velox-entrypoint] Off-heap:   ${VELOX_OFFHEAP}"
    echo "[velox-entrypoint] Spark:      ${SPARK_VERSION}"

    # start-connect-server.sh locates spark-connect_2.13-${SPARK_VERSION}.jar in
    # $SPARK_HOME/jars/ and adds it to the classpath.  spark-daemon.sh daemonizes
    # by default; SPARK_NO_DAEMONIZE=true makes it run in the foreground so the
    # container stays alive.
    export SPARK_NO_DAEMONIZE=true
    exec "${SPARK_HOME}/sbin/start-connect-server.sh" \
        --master "local[*]" \
        --jars "${GLUTEN_JAR}" \
        "${GLUTEN_CONF[@]}" \
        "--conf" "spark.connect.grpc.binding.port=${SPARK_CONNECT_PORT}"
    ;;

  run)
    # All-in-one: run benchbox inside the container with local Gluten session.
    shift
    echo "[velox-entrypoint] Running benchbox inside container (local Gluten mode)"
    echo "[velox-entrypoint] Gluten jar: ${GLUTEN_JAR}"

    exec benchbox run \
        --platform velox \
        --platform-option deployment=local \
        --platform-option "gluten_jar_path=${GLUTEN_JAR}" \
        --platform-option "offheap_size=${VELOX_OFFHEAP}" \
        "$@"
    ;;

  shell)
    exec /bin/bash
    ;;

  *)
    exec "$@"
    ;;
esac
