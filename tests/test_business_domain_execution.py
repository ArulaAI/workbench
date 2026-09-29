import threading
import pytest
from lib.context.business_domain_execution import ordered_work


def test_work_is_concurrent_bounded_and_consumed_in_input_order():
    gate=threading.Barrier(2)
    lock=threading.Lock();state={'active':0,'peak':0}
    stopping=threading.Event()
    def worker(value):
        with lock:
            state['active']+=1
            state['peak']=max(state['peak'],state['active'])
        gate.wait(timeout=3)
        with lock:state['active']-=1
        return value
    with ordered_work(range(4),worker,2,stopping) as results:
        assert list(results)==[0,1,2,3]
    assert state=={'active':0,'peak':2}
    assert not stopping.is_set()


def test_consumer_failure_stops_inflight_work():
    started=threading.Event();stopping=threading.Event();ended=threading.Event()
    def worker(value):
        if value==0:
            assert started.wait(3)
            return value
        started.set()
        assert stopping.wait(3)
        ended.set()
        return value
    with pytest.raises(RuntimeError,match='consumer stopped'):
        with ordered_work([0,1],worker,2,stopping) as results:
            assert next(results)==0
            raise RuntimeError('consumer stopped')
    assert ended.is_set()


def test_worker_stop_prevents_submission_of_queued_work():
    first_two_started=threading.Barrier(2);stopping=threading.Event();seen=[]
    lock=threading.Lock()
    def worker(value):
        with lock:seen.append(value)
        first_two_started.wait(timeout=3)
        if value==0:stopping.set()
        return value
    with ordered_work(range(10),worker,2,stopping) as results:
        assert list(results)==[0,1]
    assert sorted(seen)==[0,1]
    assert not stopping.is_set()
