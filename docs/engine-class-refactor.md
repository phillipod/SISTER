# SISTER - Engine Class Refactor

## Callbacks

| Event Name                   | When It Occurs                                                | Payload                                      | Emitted By Class       |     Notes
|-----------------------------|---------------------------------------------------------------|----------------------------------------------|-------------------------|----------------
| `on_image_loaded`           | After loading input image                                     | `{ shape, source_path }`                     | `SISTER`                |
| `on_labels_detected`        | After OCR or label detection completes                        | `{ labels: {...} }`                          | `LabelLocator`          |
| `on_build_classified`       | After identifying build type (e.g. ground vs space)           | `{ build_type, score }`                      | `BuildClassifier`       |
| `on_regions_detected`       | After computing ROIs for icon slots                           | `{ regions: {...} }`                         | `RegionDetector`        |
| `on_slots_detected`         | After detecting candidate icon slot boxes                     | `{ region: str, slots: List[Tuple] }`        | `IconSlotDetector`      |
| `on_quality_predicted`      | After overlay prediction for each slot                        | `{ region, qualities: [...] }`               | `SSIMEngine`            |
| `on_icon_candidates`        | After pHash filtering and candidate icon selection            | `{ region, num_filtered, best_score }`       | `SSIMEngine`            |
| `on_icon_slot_match_complete` | After finishing all icon matching in a specific slot        | `{ region, slot_index, matches: [...] }`     | `IconMatcher`           | 
| `on_icon_match_complete`    | After finishing all icon matching in a region                 | `{ region, matches: [...] }`                 | `IconMatcher`           |
| `on_icon_match_progress`    | During SSIM matching of a single icon candidate               | `{ region, icon_name, slot_index, score }`   | `SSIMEngine`            | This could slow matching. 
| `on_screenshot_complete`    | After full pipeline completion for one screenshot             | `{ matches: [...] }`                         | `SisterEngine`          |
| `on_error`                  | On any exception                                              | `{ stage, error, traceback }`                | Any stage               |



