from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

class PersistentProcessPoolExecutor:
    def __init__(self, max_workers=None, **kwargs):
        self._executor = ProcessPoolExecutor(max_workers=max_workers, **kwargs)
        self._shutdown = False

    def submit(self, fn, *args, **kwargs):
        if self._shutdown:
            raise RuntimeError("Executor already shutdown")
        return self._executor.submit(fn, *args, **kwargs)

    def map(self, fn, *iterables, chunksize=1):
        if self._shutdown:
            raise RuntimeError("Executor already shutdown")
        # forward to the underlying pool
        return self._executor.map(fn, *iterables, chunksize=chunksize)

    def shutdown(self, wait=True):
        self._executor.shutdown(wait)
        self._shutdown = True

    # optional: support `with` but no auto‐shutdown:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # don’t shut down on exit
        pass
