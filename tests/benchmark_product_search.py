"""Run with python -m tests.benchmark_product_search [database]; reads data only."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from statistics import median
from timeit import timeit

from mapper.core.common import normalize_search, product_search_text, normalise_sku


def benchmark(path: Path) -> None:
    # Do not instantiate WarehouseDatabase: benchmarking must never migrate live data.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        records = connection.execute("SELECT product_id,COALESCE(full_name,brand_name,product_id),COALESCE(brand_name,'') FROM catalog_products").fetchall()
    if not records:
        print("No products to benchmark.")
        return
    original = {pid: normalize_search(f"{pid} {name} {short}") for pid, name, short in records}
    dashless = {row[0]: product_search_text(*row) for row in records}
    sample = next((row for row in records if "-" in row[0]), records[0])
    queries = {
        "original ID": sample[0],
        "dashless ID": sample[0].replace("-", ""),
        "name": next((word for word in sample[1].split() if len(word) >= 3), sample[1]),
        "no match": "__no_such_product_987654321__",
    }
    print(f"{len(records):,} products; cached filtering only (excludes sorting/rendering).")
    print("Query             Before ms  After ms  Ratio  Matches before/after")
    for label, query in queries.items():
        term = normalize_search(normalise_sku(query))
        times = [[], []]
        for repeat in range(11):
            # Alternate order to reduce warm-up and scheduling bias.
            for index in (0, 1) if repeat % 2 == 0 else (1, 0):
                cache = (original, dashless)[index]
                times[index].append(timeit(
                    lambda: [pid for pid, text in cache.items() if term in text], number=25,
                ) * 1000 / 25)
        before, after = (median(values) for values in times)
        counts = [sum(term in text for text in cache.values()) for cache in (original, dashless)]
        print(f"{label:17} {before:9.3f} {after:9.3f} {after / before:6.2f}x  {counts[0]}/{counts[1]}")


if __name__ == "__main__":
    benchmark(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/warehouse_locations.db"))
