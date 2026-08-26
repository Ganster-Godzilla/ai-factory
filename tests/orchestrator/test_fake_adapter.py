from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.fake import FakeHarness


def _packet(tmp_path):
    return TaskPacket(role="dev", prompt="做任务", workdir=tmp_path,
                      artifacts_in=[], artifacts_out=[], acceptance_cmd=None,
                      budget={})


def test_fake_returns_scripted(tmp_path):
    h = FakeHarness(script=["failed", "done"])
    assert h.run(_packet(tmp_path)).status == "failed"
    assert h.run(_packet(tmp_path)).status == "done"
    assert h.run(_packet(tmp_path)).status == "done"  # 脚本用尽默认 done


def test_fake_records_packets(tmp_path):
    h = FakeHarness()
    p = _packet(tmp_path)
    h.run(p)
    assert h.received[0].prompt == "做任务"
