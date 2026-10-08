# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import sys


def main() -> None:
    from pyspark.sql import SparkSession

    database_query, query, results_path = sys.argv[1:]
    spark = SparkSession.builder.appName("BenchBox Query").enableHiveSupport().getOrCreate()
    spark.sql(database_query)
    result = spark.sql(query)
    result.write.mode("overwrite").json(results_path)
    spark.stop()


if __name__ == "__main__":
    main()
