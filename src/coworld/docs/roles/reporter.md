# Reporter Role

Reporters compress sparse episode experience into dense highlight signals. They include narrative reporters such as news
casters, interesting-moment summarizers, structured stat reporters, and rich data dump reporters that produce
machine-usable parquet stats.

Reporter inputs may include replay/results artifacts, global observations, logs, traces, and already-produced reporter
artifacts.

A stats parquet reporter should write `COGAME_REPLAY_STATS_PARQUET_URI` with these columns:

```text
ts, player, key, value
```

`player` is the player slot for player-scoped facts and `-1` for global facts.

Reporter output can be HTML intended for surfaces such as Observatory's The Column, parquet for downstream analysis, or
another runner-defined artifact bundle. The runner owns the exact archive layout so reporters can include the assets
their output needs.
