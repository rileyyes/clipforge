"""Job progress must only ever move forward, even when a step reports a
slightly lower value than before (FFmpeg's time lines can wobble)."""
from app.jobs import Job, JobContext


class _FakeManager:
    def __init__(self):
        self.values = []

    def _update(self, job_id, throttle=False, **fields):
        if "progress" in fields:
            self.values.append(fields["progress"])


def test_progress_never_goes_backwards():
    m = _FakeManager()
    ctx = JobContext(m, Job(id="j1", kind="x", project_id=None, params={}))
    for v in [0.1, 0.1583, 0.1571, 0.1583, 0.5, 0.49, 2.0]:
        ctx.progress(v)
    assert m.values == sorted(m.values)
    assert m.values[-1] == 1.0
    assert m.values[2] == 0.1583  # the dip is held at the best value


def test_progress_none_is_passed_through():
    m = _FakeManager()
    ctx = JobContext(m, Job(id="j2", kind="x", project_id=None, params={}))
    ctx.progress(0.3)
    ctx.progress(None)
    assert m.values == [0.3, None]
