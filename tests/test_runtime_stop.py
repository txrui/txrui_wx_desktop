"""停止必须唤醒等待中的异步任务，且不重建停止信号。"""
import asyncio
import threading

from txrui.runtime import Runtime


def test_stop_cancels_idle_async_task_and_joins_thread():
    runtime = Runtime()
    ready = threading.Event()
    cancelled = threading.Event()

    async def idle():
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    def run():
        loop = asyncio.new_event_loop()
        runtime.loop = loop
        try:
            loop.run_until_complete(idle())
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

    runtime.thread = threading.Thread(target=run, daemon=True)
    runtime.thread.start()
    assert ready.wait(2)
    assert runtime.stop() is True
    assert cancelled.is_set()
    assert not runtime.thread.is_alive()
    assert runtime.stop_event.is_set()
    assert runtime.stop() is True
