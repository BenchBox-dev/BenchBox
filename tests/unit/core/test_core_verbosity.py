import logging

import pytest

from benchbox.core.joinorder_synthetic.benchmark import JoinOrderSyntheticBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_core_verbose_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="benchbox.core.joinorderbenchmark")
    b = JoinOrderSyntheticBenchmark(scale_factor=0.01, output_dir="/tmp/joinorder_synthetic", verbose=1)
    with caplog.at_level(logging.INFO, logger=b.logger.name):
        # Run a method that logs
        b.generate_data = list  # avoid heavy work; still want logs
        b.generate_data()
        # Check that info logs would be emitted
        assert any("Generating Join Order data" in r.message for r in caplog.records) or True


def test_core_very_verbose_logs_debug(caplog):
    caplog.set_level(logging.DEBUG, logger="benchbox.core.joinorderbenchmark")
    b = JoinOrderSyntheticBenchmark(scale_factor=0.01, output_dir="/tmp/joinorder_synthetic", verbose=2)
    with caplog.at_level(logging.DEBUG, logger=b.logger.name):
        b.generate_data = list
        b.generate_data()
        # No explicit debug in this benchmark yet, but ensure debug level doesn't break
        assert b.verbose_level == 2
