import json

import pytest

import auditlog


@pytest.fixture
def temporary_database(monkeypatch, tmp_path):
    database = tmp_path / "audit-test.db"
    monkeypatch.setenv("DB_PATH", str(database))
    auditlog.init_db()
    return database


def test_empty_chain_verifies(temporary_database):
    assert auditlog.get_log() == []
    assert auditlog.verify_chain() == (True, None)


def test_normal_chain_verifies(temporary_database):
    first_id = auditlog.append_event("purchase-1", "requested", {"amount": 12})
    auditlog.append_event("purchase-1", "approved", {"approved": True})

    events = auditlog.get_log()
    assert [event["id"] for event in events] == [first_id, first_id + 1]
    assert events[0]["prev_hash"] == auditlog.GENESIS_HASH
    assert events[1]["prev_hash"] == events[0]["hash"]
    assert auditlog.verify_chain() == (True, None)


def test_data_tampering_is_detected(temporary_database):
    event_id = auditlog.append_event("purchase-1", "requested", {"amount": 12})
    with auditlog.connect() as db:
        db.execute(
            "UPDATE events SET data = ? WHERE id = ?",
            (json.dumps({"amount": 999}), event_id),
        )

    assert auditlog.verify_chain() == (False, event_id)


def test_previous_hash_tampering_is_detected(temporary_database):
    auditlog.append_event("purchase-1", "requested", {"amount": 12})
    second_id = auditlog.append_event("purchase-1", "approved", {"approved": True})
    with auditlog.connect() as db:
        db.execute(
            "UPDATE events SET prev_hash = ? WHERE id = ?",
            ("f" * 64, second_id),
        )

    assert auditlog.verify_chain() == (False, second_id)


def test_reports_first_broken_entry_id(temporary_database):
    first_id = auditlog.append_event("purchase-1", "requested", {"amount": 12})
    second_id = auditlog.append_event("purchase-1", "approved", {"approved": True})
    third_id = auditlog.append_event("purchase-1", "captured", {"captured": True})
    with auditlog.connect() as db:
        db.execute("UPDATE events SET data = ? WHERE id = ?", ('{"bad": true}', second_id))
        db.execute("UPDATE events SET data = ? WHERE id = ?", ('{"bad": true}', third_id))

    assert first_id < second_id < third_id
    assert auditlog.verify_chain() == (False, second_id)
