# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from datetime import datetime

import pytest


@pytest.fixture
def seed() -> int:

    return 42


@pytest.fixture
def start_date() -> datetime:

    return datetime(2019, 1, 1)


@pytest.fixture
def end_date() -> datetime:

    return datetime(2019, 12, 31)


@pytest.fixture
def test_year() -> int:

    return 2019


@pytest.fixture
def test_months() -> list[int]:

    return [1]
