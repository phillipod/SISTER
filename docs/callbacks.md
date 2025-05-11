# SISTER - Pipeline Interface

## Callbacks Overview

The SISTER pipeline exposes the following generic callbacks:

| Callback Name         | Description                                    | Arguments                             | Emitted By          |
|-----------------------|------------------------------------------------|---------------------------------------|---------------------|
| `on_progress`         | Reports overall pipeline progress              | `percent_complete: float`             | Pipeline engine     |
| `on_stage_complete`   | Notifies completion of each logical stage      | `stage_name: str`, `duration_ms: int` | Pipeline engine     |
| `on_interactive`      | Allows interactive adjustment mid-pipeline     | `context: dict`                       | Interactive handler |
| `on_pipeline_complete`| Delivers final results and summary stats       | `results: dict`, `metrics: dict`      | Pipeline engine     |
| `on_metrics_complete` | Delivers final metrics for the pipeline        | `metrics: list[dict]`                 | Pipeline engine     |
| `on_error`      | Centralized error notification for pipeline failures | `error: Exception`                    | Pipeline engine     |


## Pending Callback Extensions

These hooks are pending implementation. 

|
## Potential Callback Extensions

These hooks are under consideration and have not been implemented. They may be refined or omitted for performance reasons.

| Callback Name         | Description                                                          | Arguments                                  | Potential Emitted By |
|-----------------------|----------------------------------------------------------------------|--------------------------------------------|----------------------|
| `on_slot_ready`       | Indicates when an individual slot finishes threshold processing      | `slot_id: str`, `output: dict`             | Slot processor       |
| `on_match_progress`   | Reports incremental matching progress within a slot                  | `slot_id: str`, `matches_found: int`       | Matcher engine       |
| `on_region_processed` | Signals completion of region-based processing                        | `region_id: str`, `processed_count: int`   | Region handler       |
| `on_cache_updated`    | Emits when internal caches are refreshed or invalidated              | `cache_name: str`, `new_size: int`         | Cache manager        |
|