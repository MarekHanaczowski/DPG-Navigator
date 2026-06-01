# Benchmarks

`benchmark_heavy_paths.py` measures pure-data operations used by the preview
panel and recursive search index. Fixture creation happens outside measured
sections and all generated data is removed after the run.

Use the quick profile while changing benchmark code:

```bash
python benchmarks/benchmark_heavy_paths.py --profile quick
```

Use the default profile for comparable local measurements:

```bash
python benchmarks/benchmark_heavy_paths.py --profile default --iterations 3
```

Add `--json` when storing or comparing results programmatically. Timings depend
on the filesystem, Python version, optional dependency versions, and hardware;
the script intentionally does not enforce fixed performance thresholds in CI.

Reference measurements are stored under `baselines/`. Treat them as local
comparison points, not portable pass/fail thresholds.
