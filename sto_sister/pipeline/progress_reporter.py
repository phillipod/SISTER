from typing import Callable, Any

class StageProgressReporter:
    """
    Picklable callable for scaling a sub-task's 0–100% progress
    into an arbitrary [start…end] slice of the overall stage.
    """
    def __init__(
        self,
        stage_name: str,
        report_fn: Callable[[str, str, float], None],
        window_start: float = 0.0,
        window_end:   float = 1.0,
    ):
        self.stage_name   = stage_name
        self.report_fn    = report_fn
        self.window_start = window_start
        self.window_end   = window_end

    def __call__(self, substage: str, pct: float):
        # normalize detector pct (0–100) -> fraction
        frac = pct / 100.0
        # map into [window_start…window_end]
        win_frac = self.window_start + (self.window_end - self.window_start) * frac
        # back to 0–100
        scaled = win_frac * 100.0
        # emit via the pipeline’s report API
        self.report_fn(self.stage_name, substage, scaled)

class PipelineProgressCallback:
    """
    Picklable callable that routes any (substage, pct) or
    (stage_arg, substage, pct) call into on_progress(stage, substage, pct, ctx).
    """
    def __init__(
        self,
        on_progress_fn: Callable[[str, str, float, Any], None],
        stage: str,
        ctx: Any,
    ):
        self._on_progress = on_progress_fn
        self.stage        = stage
        self.ctx          = ctx

    def __call__(self, *args):
        # support two‐arg or three‐arg invocations
        if len(args) == 2:
            substage, pct = args
        elif len(args) == 3:
            # e.g. report(stage_arg, substage, pct)
            _, substage, pct = args
        else:
            raise TypeError(
                f"PipelineProgressCallback expected 2 or 3 args, got {len(args)}"
            )

        # forward into central on_progress(stage, substage, pct, ctx)
        return self._on_progress(self.stage, substage, pct, self.ctx)