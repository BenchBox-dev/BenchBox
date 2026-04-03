"""BenchBox result publishing: tracked, deduplicated publication of schema-v2 bundles.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

The supported publishing workflow operates on already-exported schema-v2 result
bundles produced by ``benchbox.core.results.exporter``. It does NOT re-serialize
results — it copies the canonical artifacts and records durable publication metadata.

Example usage::

    from benchbox.core.publishing import BundlePublisher, PublicationStore

    store = PublicationStore()                          # ~/.benchbox/published.json
    publisher = BundlePublisher(
        destination="/mnt/shared/benchbox/results",
        store=store,
        label="maintainer-run",
    )
    result = publisher.publish("benchmark_runs/results/tpch_sf1_duckdb.json")
    print(result.reference)   # file:///mnt/shared/benchbox/results/tpch_sf1_duckdb.json

    for rec in store.list_all():
        print(rec.pub_id, rec.reference)
"""

# ---------------------------------------------------------------------------
# Legacy prototype symbols — kept for existing test backward-compatibility.
# These are the prototype classes and should not be used by new code.
# ---------------------------------------------------------------------------
from .artifacts import (
    Artifact,
    ArtifactManager,
    ArtifactMetadata,
    ArtifactStatus,
    ArtifactType,
)
from .bundle_publisher import (
    BundlePublisher,
    BundlePublishResult,
)
from .config import (
    PublishFormat,
    PublishingConfig,
    RetentionPolicy,
    StorageConfig,
    StorageProvider,
)
from .permalink import (
    Permalink,
    PermalinkGenerator,
    PermalinkRegistry,
)
from .publisher import (
    PublishBatchResult,
    Publisher,
    PublishResult,
)
from .store import (
    PublicationRecord,
    PublicationStore,
    build_reference,
)

__all__ = [
    # New supported API
    "BundlePublisher",
    "BundlePublishResult",
    "PublicationRecord",
    "PublicationStore",
    "build_reference",
    # Legacy prototype symbols (kept for existing tests)
    "PublishFormat",
    "PublishingConfig",
    "RetentionPolicy",
    "StorageConfig",
    "StorageProvider",
    "Artifact",
    "ArtifactManager",
    "ArtifactMetadata",
    "ArtifactStatus",
    "ArtifactType",
    "Permalink",
    "PermalinkGenerator",
    "PermalinkRegistry",
    "PublishBatchResult",
    "Publisher",
    "PublishResult",
]
