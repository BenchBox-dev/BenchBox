# benchbox-agent: Linux parity sandbox for reproducing the non-service
# pr.yml gate on an Apple-silicon Mac (see AGENTS.md "Apple container Linux CI parity").
# Not a service image and NOT part of any docker-compose stack -- it backs the
# `container machine` used by `make ci-linux`. arm64 only:
#   container build --arch arm64 --tag local/benchbox-agent docker/benchbox-agent
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=automatic

# Runtime + toolchain for the gate and `uv sync --group dev`: make runs the gate
# targets (`make test-correctness-gate` / `ci-local`) and is a HARD runtime dep,
# not just build glue; build-essential compiles any sdist lacking a linux/aarch64
# wheel; git for lint/CI checks that shell out to it (skill-sync, path filters);
# curl/ca-certificates for uv's Python downloads. systemd-sysv provides /sbin/init:
# `container machine` boots the rootfs via its own init which execs /sbin/init,
# so a minimal ubuntu image (no init) fails to boot as a machine.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        make \
        pkg-config \
        systemd-sysv \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# uv pinned to the host version that maintains uv.lock -- parity over latest.
COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /uvx /usr/local/bin/

CMD ["bash"]
