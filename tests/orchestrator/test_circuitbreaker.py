from orchestrator.daemon.circuitbreaker import MAX_RETRY, consult_packet, next_action, retry_prompt
from orchestrator.daemon.ticket import new_ticket


def _t(attempts, consulted=False):
    return {"id": "task-1", "attempts": attempts, "consulted": consulted, "title": "建模型"}


def test_ladder():
    assert next_action(_t(0)) == "retry"
    assert next_action(_t(MAX_RETRY - 1)) == "retry"
    assert next_action(_t(MAX_RETRY)) == "consult"
    assert next_action(_t(MAX_RETRY, consulted=True)) == "suspend"


def test_retry_prompt_carries_context():
    p = retry_prompt(_t(1), "原始任务", "assert 1==2 failed")
    assert "原始任务" in p and "第 2 次尝试" in p and "assert 1==2" in p


def test_consult_packet(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="加缓存")
    pkt = consult_packet(_t(3), t, "exit 1: boom", tmp_path)
    assert pkt.role == "architect"
    assert "exit 1: boom" in pkt.prompt and "诊断" in pkt.prompt and "加缓存" in pkt.prompt
