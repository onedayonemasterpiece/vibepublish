"""Independent-process crash fixture. Never used by the application runtime."""
import asyncio
import os
import sys
from pathlib import Path
from adapters.imagegen import FakeImagegen
from social_operations.storage import Store
from social_operations.worker import Worker

async def main():
    db, root, stage = sys.argv[1:]
    store = Store(Path(db), clock=lambda: 1_800_000_000)
    class CrashExecutor(FakeImagegen):
        async def submit(self, request):
            with store.connection() as db:
                assert db.execute('SELECT dispatched FROM visual_jobs WHERE id=?', (request.job_key,)).fetchone()[0] == 1
            if stage == 'after_marker':
                os._exit(92)
            with (Path(root)/'submit.log').open('a') as log:
                log.write(request.job_key+'\n');log.flush();os.fsync(log.fileno())
            result = await super().submit(request)
            os._exit(93)
            return result
    worker = Worker(store, imagegen=CrashExecutor(Path(root)))
    if stage == 'before_marker':
        worker.app.visuals._request = lambda *args: os._exit(91)
    await worker.run_once()

if __name__ == '__main__':
    asyncio.run(main())
