"""T-2026-0921-004 O1 先红:CAS 硬门——双对象同载先后存→第二个
StaleTicketError 且 yaml 零污染;同对象连存不误伤;新建首存不受闸;
文件被删后持旧对象保存也拒;读路径零影响;_disk_fp 不落盘。
"""
from __future__ import annotations

import pytest

from orchestrator.daemon.ticket import (StaleTicketError, load_ticket,
                                        new_ticket, save_ticket)


@pytest.fixture
def pool(tmp_path):
    return tmp_path / "pool"


def _mk(pool, summary="s"):
    return new_ticket(pool, "ai-factory", summary, created_by="pm")


class TestStaleWriteRejected:
    def test_second_stale_object_save_raises(self, pool):
        """两对象同载一票,先后保存→第二个 StaleTicketError(lost-update 拦截)。"""
        t = _mk(pool)
        a = load_ticket(pool, t.id)
        b = load_ticket(pool, t.id)      # 同一时刻的另一份拷贝(另一进程语义)
        a.owner_role = "boss"
        save_ticket(pool, a)             # a 先写:盘上已是新内容
        b.owner_role = "qa"
        with pytest.raises(StaleTicketError):
            save_ticket(pool, b)         # b 持旧指纹:拒

    def test_yaml_unpolluted_after_reject(self, pool):
        """被拒的写不落盘:yaml 保持 a 写入的内容。"""
        t = _mk(pool)
        a = load_ticket(pool, t.id)
        b = load_ticket(pool, t.id)
        a.owner_role = "boss"
        save_ticket(pool, a)
        b.owner_role = "qa"
        with pytest.raises(StaleTicketError):
            save_ticket(pool, b)
        assert load_ticket(pool, t.id).owner_role == "boss"

    def test_stale_object_after_file_deleted_rejected(self, pool):
        """文件被删后持旧对象保存=重建幽灵票,同样拒。"""
        t = _mk(pool)
        a = load_ticket(pool, t.id)
        (pool / "tickets" / f"{t.id}.yaml").unlink()
        with pytest.raises(StaleTicketError):
            save_ticket(pool, a)


class TestNormalPathUnbroken:
    def test_same_object_consecutive_saves_ok(self, pool):
        """同对象 load→save→改→save 连存不误伤(save 后指纹自更新)。"""
        a = _mk(pool)
        a.owner_role = "boss"
        save_ticket(pool, a)
        a.owner_role = "qa"
        save_ticket(pool, a)
        assert load_ticket(pool, a.id).owner_role == "qa"

    def test_fresh_load_after_external_write_ok(self, pool):
        """他人写过后,重新 load 的对象可正常保存(指纹随 load 就位)。"""
        t = _mk(pool)
        a = load_ticket(pool, t.id)
        a.owner_role = "boss"
        save_ticket(pool, a)
        b = load_ticket(pool, t.id)      # 加载发生在 a 写之后:新指纹
        b.owner_role = "qa"
        save_ticket(pool, b)
        assert load_ticket(pool, t.id).owner_role == "qa"

    def test_new_ticket_first_save_ungated(self, pool):
        """手工构造(无指纹)首存=创建语义,不受 CAS 闸。"""
        t = _mk(pool)
        assert (pool / "tickets" / f"{t.id}.yaml").exists()

    def test_fingerprint_not_serialized(self, pool):
        """_disk_fp 是内存私有,绝不落盘(yaml 无此键)。"""
        t = _mk(pool)
        text = (pool / "tickets" / f"{t.id}.yaml").read_text(encoding="utf-8")
        assert "_disk_fp" not in text

    def test_load_sets_fingerprint(self, pool):
        t = _mk(pool)
        a = load_ticket(pool, t.id)
        assert getattr(a, "_disk_fp", None)
