from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineTask, TaskOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter

from ..utils.persistent_executor import PersistentProcessPoolExecutor

def _dummy_job(i):
    # no-op work; could also do time.sleep(0) or something trivial
    return i

class StartExecutorPoolTask(PipelineTask):
    name = "start_executor_pool"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)


    def execute(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> TaskOutput:
        report(self.name, "Starting executor pool", 0.0)
        ctx.executor_pool = PersistentProcessPoolExecutor()

        total = ctx.executor_pool._executor._max_workers
        count = 0

        with ctx.executor_pool as executor:
            # submit one dummy job per worker
            futures = [executor.submit(_dummy_job, i) for i in range(ctx.executor_pool._executor._max_workers)]
            # block until all workers have run their dummy job
            for future in futures:
                result = future.result()

                count += 1
                report(self.name, f"Started worker {count}/{total}", count / total * 100.0)
        
        ctx.executor_pool_total = count

        report(self.name, "Executor pool started", 100.0)

        return TaskOutput(ctx, ctx.executor_pool_total)

class StopExecutorPoolTask(PipelineTask):
    name = "stop_executor_pool"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

    def execute(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> TaskOutput:
        report(self.name, "Shutting down executor pool", 0.0)
        ctx.executor_pool.shutdown()
        ctx.executor_pool = None
        report(self.name, "Executor pool shut down", 100.0)

        return TaskOutput(ctx, None)
    