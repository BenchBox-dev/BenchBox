# Velox Jar Setup

This page documents the Apache Gluten release tarball and extracted Velox bundle
jar used by `docker/velox/Dockerfile`.

## Docker build flow

The checked-in Dockerfile downloads the official Apache Gluten Spark 4.0 release
tarball, verifies the published `.sha512`, then extracts the bundled Velox jar.

Build the image like this (run from the project root):

```sh
docker build \
  --platform linux/amd64 \
  -f docker/velox/Dockerfile \
  -t benchbox-velox:dev .
```

As of Apache Gluten 1.6.0, the official Spark 4.0 release tarball contains an
`amd64` jar only. The provided Dockerfile therefore targets `linux/amd64`.

## Manual verification

```sh
curl -fsSLO https://downloads.apache.org/gluten/1.6.0/apache-gluten-1.6.0-bin-spark-4.0.tar.gz
curl -fsSLO https://downloads.apache.org/gluten/1.6.0/apache-gluten-1.6.0-bin-spark-4.0.tar.gz.sha512
sha512sum -c apache-gluten-1.6.0-bin-spark-4.0.tar.gz.sha512
tar -xzf apache-gluten-1.6.0-bin-spark-4.0.tar.gz \
  gluten-velox-bundle-spark4.0_2.13-linux_amd64-1.6.0.jar
```

If you want a local hash for an extracted jar, compute it after extraction:

```sh
sha256sum gluten-velox-bundle-spark4.0_2.13-linux_amd64-1.6.0.jar
```

> **Note:** Gluten graduated from the Apache Incubator in March 2026. Current
> releases are published under `downloads.apache.org/gluten/`. Historical
> incubating releases used `downloads.apache.org/incubator/gluten/` and
> different version-directory naming.

## Known versions

When bumping `GLUTEN_VERSION` in the Dockerfile, add a row here with the
official tarball and extracted jar name.

| Version | Spark | Architecture | Release tarball | Extracted jar | Notes |
|---------|-------|--------------|-----------------|---------------|-------|
| 1.6.0 | 4.0 | amd64 | `apache-gluten-1.6.0-bin-spark-4.0.tar.gz` | `gluten-velox-bundle-spark4.0_2.13-linux_amd64-1.6.0.jar` | Dockerfile verifies the published tarball `.sha512` before extraction |

As of April 2026, Apache Gluten does not publish an official `aarch64` jar in
the Spark 4.0 release tarball. Arm64 users need a self-built jar or another
custom artifact source outside the default BenchBox Docker workflow.
