import os

from core.safety.pending import APPROVED, DENIED, OPEN, Pending, PendingStore


def _store(tmp_path):
    return PendingStore(path=os.path.join(tmp_path, "pending.jsonl"))


def test_add_and_list(tmp_path):
    store = _store(tmp_path)
    item = store.add(Pending(action="restart_service", target="api-gateway", run_id="r1"))
    assert item.id
    assert store.list(run_id="r1")[0].status == OPEN
    assert store.list(run_id="other") == []


def test_resolve_is_idempotent(tmp_path):
    store = _store(tmp_path)
    item = store.add(Pending(action="scale_out", target="pay", run_id="r1"))

    store.resolve(item.id, approved=True, by="zhaoxin")
    store.resolve(item.id, approved=False, by="someone-else")  # 重复回答不该翻转结论

    assert store.get(item.id).status == APPROVED
    assert store.get(item.id).by == "zhaoxin"


def test_survives_reload(tmp_path):
    path = os.path.join(tmp_path, "pending.jsonl")
    store = PendingStore(path=path)
    item = store.add(Pending(action="restart_service", target="a", run_id="r1"))
    store.resolve(item.id, approved=False)

    reopened = PendingStore(path=path)
    assert reopened.get(item.id).status == DENIED
    assert reopened.summary(run_id="r1")["denied"] == 1


def test_summary_counts(tmp_path):
    store = _store(tmp_path)
    a = store.add(Pending(action="restart_service", target="a", run_id="r1"))
    store.add(Pending(action="scale_out", target="b", run_id="r1"))
    store.resolve(a.id, approved=True)

    assert store.summary(run_id="r1") == {"total": 2, "open": 1, "approved": 1, "denied": 0}


def test_resolve_unknown_raises(tmp_path):
    store = _store(tmp_path)
    try:
        store.resolve("nope", approved=True)
    except KeyError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("应该抛 KeyError")
