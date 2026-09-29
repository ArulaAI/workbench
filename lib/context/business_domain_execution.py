"""Bounded concurrent interpretation with deterministic result consumption."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager


@contextmanager
def ordered_work(items,worker,concurrency,stopping):
    executor=ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix='domain-interpretation')
    pending=deque();remaining=iter(items)
    def submit_one():
        if stopping.is_set():return
        try:item=next(remaining)
        except StopIteration:return
        pending.append(executor.submit(worker,item))
    def results():
        for _ in range(concurrency):submit_one()
        while pending:
            result=pending.popleft().result()
            yield result
            submit_one()
    try:
        yield results()
    finally:
        stopping.set()
        executor.shutdown(wait=True,cancel_futures=True)
        stopping.clear()
