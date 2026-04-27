# BenchBox - Apache Gluten + Velox Acceleration Image
#
# Builds a linux/amd64 image containing:
#   - Apache Spark 4.0.2 (JDK 17, Python 3.12, Scala 2.13)
#   - Gluten Velox bundle jar (extracted from the official Apache release tarball)
#   - BenchBox (installed from the local source tree)
#
# Build (single arch, quick dev build):
#   docker build --platform linux/amd64 -f docker/velox/Dockerfile -t benchbox-velox:dev .
#
# Build (distribution, requires docker buildx):
#   docker buildx build \
#     --platform linux/amd64 \
#     -f docker/velox/Dockerfile \
#     -t benchbox-velox:1.6.0 \
#     --push .
#
# IMPORTANT - macOS / Windows users:
#   You CANNOT run the Gluten bundle jar natively on macOS or Windows.
#   Build this image and use it instead. As of Apache Gluten 1.6.0, the
#   official release tarball only ships an amd64 Velox bundle jar, so the
#   checked-in Dockerfile targets linux/amd64 only. Apple Silicon can run the
#   image under emulation for smoke testing, but benchmark timings are invalid
#   under Rosetta/QEMU. Use a native x86_64 Linux host for timing-valid runs.
#
# Jar provenance:
#   Download URLs and release-tarball verification steps are in
#   docs/platforms/velox_jar_setup.md. This Dockerfile downloads the official
#   Apache release tarball at build time and verifies its published SHA-512.

FROM apache/spark:4.0.2-scala2.13-java17-python3-ubuntu

ARG GLUTEN_VERSION=1.6.0
# TARGETARCH is set automatically by docker buildx: "amd64" or "arm64"
ARG TARGETARCH

LABEL org.opencontainers.image.title="BenchBox Velox"
LABEL org.opencontainers.image.description="BenchBox + Apache Gluten + Velox on Spark 4.0.2"
LABEL org.opencontainers.image.version="${GLUTEN_VERSION}"

USER root

# Install Python package manager and BenchBox runtime dependencies.
# pip is pre-installed in the apache/spark image; install uv for consistency.
RUN pip install --no-cache-dir uv

# Detect the Spark version from the installed PySpark distribution and store it
# in /opt/spark/SPARK_VERSION.  The apache/spark base image does not export
# SPARK_VERSION, but start-connect-server.sh needs it to locate the
# spark-connect_2.13-${SPARK_VERSION}.jar inside $SPARK_HOME/jars/.
# Deriving it here keeps the version in one place: bump the FROM tag and this
# layer automatically picks up the new version.
# Also downloads the spark-connect jar (absent from the apache/spark base image)
# and verifies its SHA-1 from Maven Central (Maven Central serves .sha1 files
# alongside every artifact - same integrity-check pattern used for the Gluten
# tarball below, just with the SHA flavour Maven Central publishes).
RUN set -eux; \
    SPARK_VER="$(grep '__version__' "${SPARK_HOME}/python/pyspark/version.py" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"; \
    [ -n "${SPARK_VER}" ] || { echo "FATAL: could not detect Spark version from PySpark"; exit 1; }; \
    echo "${SPARK_VER}" > /opt/spark/SPARK_VERSION; \
    echo "Detected Spark ${SPARK_VER}"; \
    SC_BASE_URL="https://repo1.maven.org/maven2/org/apache/spark/spark-connect_2.13/${SPARK_VER}"; \
    SC_JAR="spark-connect_2.13-${SPARK_VER}.jar"; \
    cd /opt/spark/jars; \
    curl -fsSL "${SC_BASE_URL}/${SC_JAR}" -o "${SC_JAR}"; \
    curl -fsSL "${SC_BASE_URL}/${SC_JAR}.sha1" -o "${SC_JAR}.sha1"; \
    echo "$(cat "${SC_JAR}.sha1")  ${SC_JAR}" | sha1sum -c -; \
    rm -f "${SC_JAR}.sha1"

# Download the Gluten Velox bundle jar from the official Apache release tarball.
# Apache publishes a SHA-512 alongside the tarball; verify that first, then
# extract the bundled jar from the verified archive.
RUN set -eux; \
    if [ "${TARGETARCH}" != "amd64" ]; then \
        echo "ERROR: Apache Gluten ${GLUTEN_VERSION} publishes only an amd64 release jar in the official Spark 4.0 tarball."; \
        echo "       TARGETARCH=${TARGETARCH} is unsupported by the checked-in Dockerfile."; \
        echo "       Use --platform linux/amd64, or provide a custom aarch64 jar outside this default workflow."; \
        exit 1; \
    fi; \
    JAR_NAME="gluten-velox-bundle-spark4.0_2.13-linux_amd64-${GLUTEN_VERSION}.jar"; \
    RELEASE_TARBALL="apache-gluten-${GLUTEN_VERSION}-bin-spark-4.0.tar.gz"; \
    MIRROR="https://downloads.apache.org/gluten/${GLUTEN_VERSION}"; \
    cd /tmp; \
    curl -fsSLO "${MIRROR}/${RELEASE_TARBALL}"; \
    curl -fsSLO "${MIRROR}/${RELEASE_TARBALL}.sha512"; \
    sha512sum -c "${RELEASE_TARBALL}.sha512"; \
    tar -xOf "${RELEASE_TARBALL}" "${JAR_NAME}" > /opt/gluten.jar; \
    rm -f "${RELEASE_TARBALL}" "${RELEASE_TARBALL}.sha512"; \
    echo "Extracted: ${JAR_NAME} -> /opt/gluten.jar"

# Build a thin Hadoop CompressionCodec that delegates to zstd-jni.
# The official apache/spark Docker image ships Hadoop 3.4.1 whose
# ZStandardCodec requires native libhadoop compiled with zstd support, which
# this image does NOT provide.  ZstdJniCodec wraps ZstdInputStream from the
# zstd-jni-*.jar already on the classpath, giving Spark a working .zst codec
# without any native library changes.  The entrypoint registers it via
# spark.hadoop.io.compression.codecs so Hadoop auto-detects .zst files.
COPY docker/velox/ZstdJniCodec.java /tmp/ZstdJniCodec.java
RUN set -eux; \
    mkdir -p /tmp/codec_build/io/benchbox/codec; \
    cp /tmp/ZstdJniCodec.java /tmp/codec_build/io/benchbox/codec/; \
    ZSTD_JNI_JAR="$(ls /opt/spark/jars/zstd-jni-*.jar 2>/dev/null | head -1)"; \
    HADOOP_API_JAR="$(ls /opt/spark/jars/hadoop-client-api-*.jar 2>/dev/null | head -1)"; \
    [ -n "${ZSTD_JNI_JAR}" ] || { echo "FATAL: zstd-jni-*.jar not found in /opt/spark/jars/"; exit 1; }; \
    [ -n "${HADOOP_API_JAR}" ] || { echo "FATAL: hadoop-client-api-*.jar not found in /opt/spark/jars/"; exit 1; }; \
    javac -cp "${ZSTD_JNI_JAR}:${HADOOP_API_JAR}" \
          -d /tmp/codec_build \
          /tmp/codec_build/io/benchbox/codec/ZstdJniCodec.java; \
    jar cf /opt/spark/jars/benchbox-zstd-codec.jar -C /tmp/codec_build .; \
    rm -rf /tmp/codec_build /tmp/ZstdJniCodec.java; \
    echo "Built: /opt/spark/jars/benchbox-zstd-codec.jar"

# Copy BenchBox source and install with the velox extra (pulls pyspark[connect]).
# uv handles PEP 517 extras correctly; pip 22.x (Ubuntu) silently drops extras
# when building a local-directory wheel, so pyspark would never be installed.
COPY --chown=spark:spark . /opt/benchbox
RUN uv pip install --system --no-cache "/opt/benchbox[velox]"

# Entrypoint handles two modes: Spark-Connect server and one-shot benchbox run.
COPY docker/velox/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Default to the spark user (matches apache/spark base image convention).
USER spark

# Spark-Connect port (remote mode clients connect here).
EXPOSE 50051

ENTRYPOINT ["/entrypoint.sh"]
CMD ["connect"]
