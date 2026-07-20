"""List-target gate — the mechanical writability write boundary.

Mirrors test_strict_tags.py in shape: pure-policy unit tests for the smart/locked
judgement plus the on/off enforcement flow.
"""

from unittest.mock import MagicMock

from rtm_mcp.error_codes import ErrorCode
from rtm_mcp.list_targets import check_target, enforce_list_target, guided_error


def _client(enabled: bool) -> MagicMock:
    client = MagicMock()
    client.config = MagicMock(strict_list_targets=enabled)
    return client


def _resolved(**flags) -> dict:
    lst = {"id": "123", "name": "Target", "smart": False, "locked": False, "archived": False}
    lst.update(flags)
    return {"list_id": lst["id"], "list": lst}


class TestCheckTarget:
    def test_writable_list_passes(self):
        assert check_target(_resolved()["list"]) is None

    def test_smart_list_is_rejected(self):
        code, reason = check_target(_resolved(smart=True)["list"])
        assert code is ErrorCode.SMART_LIST_TARGET
        assert "smart list" in reason

    def test_locked_list_is_rejected(self):
        code, reason = check_target(_resolved(locked=True)["list"])
        assert code is ErrorCode.LOCKED_SYSTEM_LIST
        assert "locked system list" in reason

    def test_smart_takes_precedence_when_both_flags_set(self):
        """Deterministic verdict — one input can only ever produce one code."""
        code, _ = check_target(_resolved(smart=True, locked=True)["list"])
        assert code is ErrorCode.SMART_LIST_TARGET

    def test_archived_list_is_not_gated(self):
        """Mechanical writability only: RTM still accepts items into an archived list,
        so refusing one would be policy the server does not own."""
        assert check_target(_resolved(archived=True)["list"]) is None

    def test_missing_flags_default_to_allowed(self):
        assert check_target({}) is None


class TestEnforceListTarget:
    def test_off_is_inert_even_for_a_smart_list(self):
        assert (
            enforce_list_target(_client(False), _resolved(smart=True), "View", tool="add_task")
            is None
        )

    def test_absent_config_attribute_is_inert(self):
        client = MagicMock()
        client.config = MagicMock(spec=[])  # no strict_list_targets attribute
        assert enforce_list_target(client, _resolved(smart=True), "View", tool="add_task") is None

    def test_on_allows_a_writable_list(self):
        assert enforce_list_target(_client(True), _resolved(), "Work", tool="add_task") is None

    def test_on_rejects_a_smart_list(self, caplog):
        with caplog.at_level("INFO"):
            err = enforce_list_target(_client(True), _resolved(smart=True), "View", tool="add_task")
        assert err["error"]["code"] == ErrorCode.SMART_LIST_TARGET
        assert "strict_list_targets rejected" in caplog.text

    def test_on_rejects_a_locked_list(self):
        err = enforce_list_target(_client(True), _resolved(locked=True), "Inbox", tool="move_task")
        assert err["error"]["code"] == ErrorCode.LOCKED_SYSTEM_LIST


class TestGuidedError:
    def test_carries_the_code_and_recovery_material(self):
        err = guided_error("View", ErrorCode.SMART_LIST_TARGET, "it is a smart list")
        body = err["error"]
        assert body["code"] == ErrorCode.SMART_LIST_TARGET
        assert "View" in body["message"]
        details = body["details"]
        assert details["rejected_list"] == "View"
        assert details["strict_list_targets_mode"] is True
        assert "get_lists" in details["how_to_proceed"]
        assert "RTM_STRICT_LIST_TARGETS" in details["how_to_proceed"]

    def test_how_to_proceed_points_at_the_plugin_for_canonical_policy(self):
        """Which writable list is CORRECT is plugin-owned — the guidance must say so."""
        detail = guided_error("Processed", ErrorCode.SMART_LIST_TARGET, "x")["error"]["details"]
        assert "list-catalogue" in detail["how_to_proceed"]
