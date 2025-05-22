from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional

import numpy as np


@dataclass(frozen=True)
class Slot:
    region_label: str
    index: int
    bbox: Tuple[int, int, int, int]

@dataclass
class PipelineState:
    screenshot: np.ndarray
    config: Dict[str, Any] = field(default_factory=dict)
    app_config: Dict[str, Any] = field(default_factory=dict)
    labels: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)
    regions: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)
    slots: Dict[str, List[Slot]] = field(default_factory=dict)
    classification: Dict[Slot, Any] = field(default_factory=dict)
    predicted_qualities: Any = None
    predicted_icons: Any = None
    found_icons: Any = None
    filtered_icons: Any = None


@dataclass
class StageOutput:
    """
    Holds the context after a stage and any stage-specific output.
    """

    context: PipelineState
    output: Any


# --- Abstract Stage ---
class Stage:
    name: str = ""
    interactive: bool = False

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        self.opts = opts
        self.app_config = app_config

    def run(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        """
        Execute the stage, updating ctx in place or returning a new one.
        Use report(stage_name, percent_complete) to emit progress.
        """
        raise NotImplementedError
