import logging
import threading
from types import SimpleNamespace

from benchbox.core.throughput.result import ThroughputResult
from benchbox.core.throughput.runner import StreamRunner


def hung_stream(stream_id, seed, config):
    threading.Event().wait(60)


config = SimpleNamespace(
    num_streams=2, max_workers=None, base_seed=1, stream_timeout=1, scale_factor=1.0, verbose=False
)
result = ThroughputResult(
    start_time="", end_time="", total_time=0.0, throughput_at_size=0.0, streams_executed=0, streams_successful=0
)
StreamRunner.execute(hung_stream, config, result, logging.getLogger("probe"))
print("OUTSTANDING", result.outstanding_stream_ids, flush=True)
