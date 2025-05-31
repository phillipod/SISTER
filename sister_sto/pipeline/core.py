from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional, Union

import numpy as np


@dataclass(frozen=True)
class Slot:
    icon_group_label: str
    index: int
    bbox: Tuple[int, int, int, int]


@dataclass
class PipelineState:
    screenshots: Union[np.ndarray, List[np.ndarray], None]
    config: Dict[str, Any] = field(default_factory=dict)
    app_config: Dict[str, Any] = field(default_factory=dict)
    executor_pool: Any = None
    labels: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)
    icon_groups: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)
    slots: Dict[str, List[Slot]] = field(default_factory=dict)
    classifications: List[Dict[Slot, Any]] = field(default_factory=dict)
    classification: Dict[Slot, Any] = field(default_factory=dict)
    detected_overlays: Any = None
    prefiltered_icons: Any = None
    found_icons: Any = None
    filtered_icons: Any = None

    def __post_init__(self):
        # normalize to a list
        if not self.screenshots is None:
            self.set_screenshots(self.screenshots)

    def copy(self) -> "PipelineState":
        """
        Create a fresh run-state that reuses only config, app_config, and executor_pool.
        All other fields are reset to their defaults.
        """
        return PipelineState(
            screenshots=None,
            config=self.config,
            app_config=self.app_config,
            executor_pool=self.executor_pool,
        )

    def set_screenshots(self, screenshots: Union[np.ndarray, List[np.ndarray]]):
        if isinstance(screenshots, np.ndarray):
            self.screenshots = [screenshots]
        elif isinstance(screenshots, list):
            self.screenshots = screenshots
        else: 
            raise TypeError(f"PipelineState.screenshots must be ndarray or list, got {type(screenshots)}")

    @property
    def screenshot(self) -> np.ndarray:
        """
        Alias to the first screenshot, for any legacy code that
        still expects `state.screenshot` to be a single image.
        """
        return self.screenshots[0]

@dataclass
class StageOutput:
    """
    Holds the context after a stage and any stage-specific output.
    """

    context: PipelineState
    output: Any

@dataclass
class TaskOutput:
    """
    Holds the context after a task and any task-specific output.
    """

    context: PipelineState
    output: Any



# --- Abstract PipelineStage ---
class PipelineStage:
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


# --- Abstract PipelineStage ---
class PipelineTask:
    name: str = ""
    interactive: bool = False

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        self.opts = opts
        self.app_config = app_config

    def execute(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> TaskOutput:
        """
        Execute the task, updating ctx in place or returning a new one.
        Use report(stage_name, percent_complete) to emit progress.
        """
        raise NotImplementedError
