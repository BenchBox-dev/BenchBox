# API Reference

```{tags} reference, python-api
```

This page lists the benchmark classes and the import path to use for each. For detailed API documentation, see {doc}`reference/python-api/index`.

Each benchmark class takes `scale_factor` and `output_dir` and inherits from `BaseBenchmark`; see {doc}`reference/python-api/base` for the methods they share. The canonical import is the one exported from the top-level `benchbox` package. The module import in the third column returns the same object.

| Benchmark | Canonical import | Module import | Contract |
| --- | --- | --- | --- |
| AMPLab Big Data | `from benchbox import AMPLab` | `from benchbox.amplab import AMPLab` | {doc}`reference/python-api/benchmarks/amplab` |
| Base class | `from benchbox import BaseBenchmark` | `from benchbox.base import BaseBenchmark` | {doc}`reference/python-api/base` |
| ClickBench | `from benchbox import ClickBench` | `from benchbox.clickbench import ClickBench` | {doc}`reference/python-api/benchmarks/clickbench` |
| CoffeeShop | `from benchbox import CoffeeShop` | `from benchbox.coffeeshop import CoffeeShop` | {doc}`reference/python-api/benchmarks/coffeeshop` |
| Data Vault | `from benchbox import DataVault` | `from benchbox.datavault import DataVault` | {doc}`reference/python-api/benchmarks/datavault` |
| Flight Data | `from benchbox import FlightData` | `from benchbox.flightdata import FlightData` | {doc}`reference/python-api/benchmarks/flightdata` |
| H2O.ai database benchmark | `from benchbox import H2ODB` | `from benchbox.h2odb import H2ODB` | {doc}`reference/python-api/benchmarks/h2odb` |
| Join Order | `from benchbox import JoinOrder` | `from benchbox.joinorder import JoinOrder` | {doc}`reference/python-api/benchmarks/joinorder` |
| Metadata Primitives | `from benchbox import MetadataPrimitives` | `from benchbox.metadata_primitives import MetadataPrimitives` | {doc}`reference/python-api/benchmarks/metadata-primitives` |
| NYC Taxi | `from benchbox import NYCTaxi` | `from benchbox.nyctaxi import NYCTaxi` | {doc}`reference/python-api/benchmarks/nyctaxi` |
| Read Primitives | `from benchbox import ReadPrimitives` | `from benchbox.read_primitives import ReadPrimitives` | {doc}`reference/python-api/benchmarks/read-primitives` |
| Star Schema Benchmark | `from benchbox import SSB` | `from benchbox.ssb import SSB` | {doc}`reference/python-api/benchmarks/ssb` |
| TPC-DI | `from benchbox import TPCDI` | `from benchbox.tpcdi import TPCDI` | {doc}`reference/python-api/benchmarks/tpcdi` |
| TPC-DS | `from benchbox import TPCDS` | `from benchbox.tpcds import TPCDS` | {doc}`reference/python-api/benchmarks/tpcds` |
| TPC-DS One Big Table | `from benchbox import TPCDSOBT` | `from benchbox.tpcds_obt import TPCDSOBT` | {doc}`reference/python-api/benchmarks/tpcds-obt` |
| TPC-H | `from benchbox import TPCH` | `from benchbox.tpch import TPCH` | {doc}`reference/python-api/benchmarks/tpch` |
| TPC-Havoc | `from benchbox import TPCHavoc` | `from benchbox.tpchavoc import TPCHavoc` | {doc}`reference/python-api/benchmarks/tpchavoc` |
| TPC-H Skew | `from benchbox import TPCHSkew` | `from benchbox.tpch_skew import TPCHSkew` | {doc}`reference/python-api/benchmarks/tpch-skew` |
| Transaction Primitives | `from benchbox import TransactionPrimitives` | `from benchbox.transaction_primitives import TransactionPrimitives` | {doc}`reference/python-api/benchmarks/transaction-primitives` |
| TSBS DevOps | `from benchbox import TSBSDevOps` | `from benchbox.tsbs_devops import TSBSDevOps` | {doc}`reference/python-api/benchmarks/tsbs-devops` |
| Vector Search | `from benchbox import VectorSearch` | `from benchbox.vector_search import VectorSearch` | {doc}`reference/python-api/benchmarks/vector-search` |
| Write Primitives | `from benchbox import WritePrimitives` | `from benchbox.write_primitives import WritePrimitives` | {doc}`reference/python-api/benchmarks/write-primitives` |

TPC-DI needs the `tpcdi` extra (`pip install "benchbox[tpcdi]"`).
