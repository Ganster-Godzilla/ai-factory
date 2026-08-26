"""M1 验收:一张假工单从 draft 走到 done,事件日志完整。"""
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import APPROVALS, transition
from orchestrator.daemon.ticket import load_ticket, new_ticket


def test_full_lifecycle_with_fake_harness(pool, tmp_path):
    h = FakeHarness()
    t = new_ticket(pool, project="quant-lab", summary="给报表加缓存", created_by="probe")

    transition(pool, t, "p0_proposed", actor="pm")
    for state in ["p0_proposed", "p1_proposed"]:
        transition(pool, load_ticket(pool, t.id), APPROVALS[state], actor="boss")
        advance_once(pool, t.id, h, tmp_path)
    # p2: architect 干完后老板批
    transition(pool, load_ticket(pool, t.id), "p2_approved", actor="boss")
    advance_once(pool, t.id, h, tmp_path)   # auto→p3_running
    advance_once(pool, t.id, h, tmp_path)   # p3 无 tasks,auto→p4(不再产生 dev role_run)
    advance_once(pool, t.id, h, tmp_path)   # qa→p5_ready
    transition(pool, load_ticket(pool, t.id), "p5_releasing", actor="boss")
    advance_once(pool, t.id, h, tmp_path)   # release→monitoring
    advance_once(pool, t.id, h, tmp_path)   # sre→done

    assert load_ticket(pool, t.id).state == "done"
    kinds = [e["event"] for e in read_events(pool, t.id)]
    assert kinds[0] == "created"
    assert "state_changed" in kinds and "role_run" in kinds
    roles = [e["actor"] for e in read_events(pool, t.id) if e["event"] == "role_run"]
    # dev 不再出现在角色级 role_run 中:p3_running 已改为任务级派发(run_dev_tasks),
    # 空 tasks 工单直接 auto 到 p4_verifying。dev 任务级派发路径由
    # test_routing.py 的 test_p3_dispatches_ready_tasks 覆盖。
    assert roles == ["pm", "architect", "qa", "release", "sre"]
