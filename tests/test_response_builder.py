"""Tests for response builder."""

from unittest.mock import MagicMock, PropertyMock

from rtm_mcp.parsers import (
    entity_handle,
    format_list,
    format_task,
    parse_lists_response,
    parse_tasks_response,
    priority_to_code,
    repeat_kind,
)
from rtm_mcp.response_builder import (
    build_response,
    get_transaction_info,
    record_and_build_response,
    redact_secrets,
)


class TestRedactSecrets:
    """Test credential redaction in reflected payloads."""

    def test_masks_secret_keys_case_insensitively(self) -> None:
        out = redact_secrets({"api_key": "k", "Auth_Token": "t", "API_SIG": "s", "stat": "ok"})
        assert out == {
            "api_key": "***redacted***",
            "Auth_Token": "***redacted***",
            "API_SIG": "***redacted***",
            "stat": "ok",
        }

    def test_recurses_nested_containers(self) -> None:
        out = redact_secrets({"rsp": {"auth_token": "t", "items": [{"api_sig": "s"}]}, "ok": True})
        assert out["rsp"]["auth_token"] == "***redacted***"
        assert out["rsp"]["items"][0]["api_sig"] == "***redacted***"
        assert out["ok"] is True

    def test_does_not_mutate_input(self) -> None:
        src = {"api_key": "k", "stat": "ok"}
        redact_secrets(src)
        assert src["api_key"] == "k"

    def test_passthrough_non_containers(self) -> None:
        assert redact_secrets("hello") == "hello"
        assert redact_secrets(42) == 42
        assert redact_secrets(None) is None


class TestBuildResponse:
    """Test response building."""

    def test_basic_response(self) -> None:
        """Test basic response structure."""
        result = build_response(data={"key": "value"})

        assert "data" in result
        assert "metadata" in result
        assert result["data"]["key"] == "value"
        assert "fetched_at" in result["metadata"]

    def test_with_analysis(self) -> None:
        """Test response with analysis."""
        result = build_response(
            data={"key": "value"},
            analysis={"insights": ["test insight"]},
        )

        assert "analysis" in result
        assert result["analysis"]["insights"] == ["test insight"]

    def test_with_transaction_id(self) -> None:
        """Test response with transaction ID."""
        result = build_response(
            data={"key": "value"},
            transaction_id="tx123",
        )

        assert result["metadata"]["transaction_id"] == "tx123"

    def test_with_transaction_undoable(self) -> None:
        """Test response with transaction_undoable flag."""
        result = build_response(
            data={"key": "value"},
            transaction_id="tx123",
            transaction_undoable=True,
        )

        assert result["metadata"]["transaction_undoable"] is True

    def test_with_timeline_id(self) -> None:
        """Test response with timeline_id."""
        result = build_response(
            data={"key": "value"},
            transaction_id="tx123",
            timeline_id="tl456",
        )

        assert result["metadata"]["timeline_id"] == "tl456"

    def test_undoable_false_not_included_without_transaction(self) -> None:
        """Test that transaction_undoable None is not included."""
        result = build_response(data={"key": "value"})

        assert "transaction_undoable" not in result["metadata"]
        assert "timeline_id" not in result["metadata"]


class TestGetTransactionInfo:
    """Test transaction info extraction."""

    def test_with_undoable_transaction(self) -> None:
        result = {"transaction": {"id": "tx1", "undoable": "1"}}
        tx_id, undoable = get_transaction_info(result)
        assert tx_id == "tx1"
        assert undoable is True

    def test_with_non_undoable_transaction(self) -> None:
        result = {"transaction": {"id": "tx2", "undoable": "0"}}
        tx_id, undoable = get_transaction_info(result)
        assert tx_id == "tx2"
        assert undoable is False

    def test_with_no_transaction(self) -> None:
        result = {"stat": "ok"}
        tx_id, undoable = get_transaction_info(result)
        assert tx_id is None
        assert undoable is False

    def test_with_empty_transaction(self) -> None:
        result = {"transaction": {}}
        tx_id, undoable = get_transaction_info(result)
        assert tx_id is None
        assert undoable is False


class TestRecordAndBuildResponse:
    """Test the combined record + build helper."""

    def test_records_and_builds(self) -> None:
        client = MagicMock()
        type(client).timeline_id = PropertyMock(return_value="tl100")

        result = {"transaction": {"id": "tx1", "undoable": "1"}}
        data = {"message": "Task added"}

        response = record_and_build_response(client, result, data, "add_task")

        client.record_transaction.assert_called_once_with("tx1", "add_task", True, "Task added")
        assert response["metadata"]["transaction_id"] == "tx1"
        assert response["metadata"]["transaction_undoable"] is True
        assert response["metadata"]["timeline_id"] == "tl100"
        assert response["data"]["message"] == "Task added"

    def test_no_transaction_in_result(self) -> None:
        client = MagicMock()

        result = {"stat": "ok"}
        data = {"message": "Done"}

        response = record_and_build_response(client, result, data, "some_tool")

        client.record_transaction.assert_not_called()
        assert "transaction_id" not in response["metadata"]

    def test_uses_tool_name_as_fallback_summary(self) -> None:
        client = MagicMock()
        type(client).timeline_id = PropertyMock(return_value="tl1")

        result = {"transaction": {"id": "tx1", "undoable": "1"}}
        data = {"result": "ok"}  # no "message" key

        record_and_build_response(client, result, data, "custom_tool")

        client.record_transaction.assert_called_once_with("tx1", "custom_tool", True, "custom_tool")


class TestPriorityConversion:
    """Test priority code conversion."""

    def test_number_priorities(self) -> None:
        """Test numeric priority conversion."""
        assert priority_to_code(1) == "1"
        assert priority_to_code(2) == "2"
        assert priority_to_code(3) == "3"
        assert priority_to_code(0) == "N"

    def test_string_priorities(self) -> None:
        """Test string priority conversion."""
        assert priority_to_code("high") == "1"
        assert priority_to_code("medium") == "2"
        assert priority_to_code("low") == "3"
        assert priority_to_code("none") == "N"
        assert priority_to_code("N") == "N"

    def test_case_insensitive(self) -> None:
        """Test case insensitivity."""
        assert priority_to_code("HIGH") == "1"
        assert priority_to_code("Medium") == "2"

    def test_none_value(self) -> None:
        """Test None handling."""
        assert priority_to_code(None) == "N"


class TestRepeatKind:
    """The recurrence-kind classifier.

    RTM's `<rrule every="0|1">` attribute is the ONLY place this fact is available — MilkScript
    exposes a bare `isRecurring()`, `rtm.Recurrence` is a write-only builder, and the search
    syntax has `isRepeating:true` but no repeat-TYPE operator. Until v6.8.0 the whole element was
    collapsed to a boolean one line into the parser and the attribute was discarded.
    """

    def test_every_one_is_an_every_repeat(self) -> None:
        """The live shape: `every` arrives as the STRING "1" alongside the rule text in `$t`."""
        assert repeat_kind({"every": "1", "$t": "FREQ=WEEKLY;INTERVAL=1;WKST=MO"}) == "every"

    def test_every_zero_is_an_after_repeat(self) -> None:
        """`every="0"` is an after-type repeat — 27 of these were live on 2026-08-03."""
        assert repeat_kind({"every": "0", "$t": "FREQ=YEARLY;INTERVAL=1;WKST=MO"}) == "after"

    def test_no_rule_is_none(self) -> None:
        """A one-off series has no rrule at all."""
        assert repeat_kind(None) is None

    def test_a_rule_with_no_readable_every_is_unclassified_never_guessed(self) -> None:
        """The fourth case, and the one that must NOT default to "every".

        A wrong "every" is exactly the silent-wrong-identity failure this exists to prevent: a
        caller keying durable state on `taskseries_id` would key it on an id that re-keys, and
        nothing would say so. Unreadable must read as unreadable.
        """
        assert repeat_kind({"$t": "FREQ=WEEKLY;INTERVAL=1"}) is None
        assert repeat_kind({"every": "yes"}) is None
        assert repeat_kind({"every": None}) is None
        # A shape this function does not recognise at all is still not a guess.
        assert repeat_kind("FREQ=WEEKLY") is None

    def test_tolerates_a_non_string_every(self) -> None:
        """The attribute is a string on the wire, but the classifier must not hinge on that.

        If the JSON conversion ever coerces it, `1`/`True` must still read "every" rather than
        silently falling through to the unclassified branch and stranding every repeating item.
        """
        assert repeat_kind({"every": 1}) == "every"
        assert repeat_kind({"every": True}) == "every"
        assert repeat_kind({"every": 0}) == "after"
        assert repeat_kind({"every": False}) == "after"

    def test_the_deductive_cross_check_is_retracted(self) -> None:
        """v6.8.0's "a series with >=2 tasks is provably every" is FALSE. Pinned by counter-example.

        The claim was verified over `status:incomplete` (31 series) and generalised to the whole
        account. Over all 44,730 tasks (2026-08-03) **11 `after` series hold >=2 tasks**, the
        largest 86 deep — `226592019` "Taken protein shake?", every task carrying `every="0"`.
        An `after` series accumulates its completed occurrences exactly as an `every` one does;
        what re-keys is the series a NEW occurrence lands in, not the history already recorded.
        (The reason the subset held: an `after` series has at most ONE open occurrence, because
        the next is minted only on completion.)

        The test it replaces asserted `repeat_kind({"every": "1"}) == "every"` and called that
        the cross-check — it could not have failed whatever the live data said, which is how a
        false claim shipped with a green suite. This one uses the real counter-example.
        """
        # The live shape from series 226592019 — 86 tasks in ONE series, and it is NOT "every".
        after_series_with_86_tasks = {"every": "0", "$t": "FREQ=DAILY;INTERVAL=1;WKST=MO"}
        assert repeat_kind(after_series_with_86_tasks) == "after"

    def test_counting_occurrences_says_nothing_in_the_other_direction_either(self) -> None:
        """A series with many tasks may not repeat AT ALL — 325 live ones do exactly that.

        Deleting a recurrence rule leaves its occurrence history behind: series `147643653`
        ("Weekly GTD review") holds 31 tasks and carries no rrule. So neither `is_repeating` nor
        the kind can be inferred from a count in either direction, and `rrule/@every` is the only
        discriminator.
        """
        assert repeat_kind(None) is None  # 31 tasks, no rule — not repeating, kind unknowable


class TestEntityHandle:
    """The durable GTD entity handle — ONE id with ONE meaning (Piece 1, v6.9.0).

    Exists so a consumer never chooses between `task_id` and `taskseries_id`, and never learns
    RTM has two recurrence kinds. The mixup is measured: on 2026-08-02 six of 37 rename ids were
    `taskseries_id`s passed as `task_id`s.
    """

    def test_a_one_off_is_its_own_task_id(self) -> None:
        assert entity_handle(task_id="1195027990", taskseries_id="605236582", repeat_kind=None) == (
            "1195027990",
            False,
        )

    def test_an_every_repeat_is_its_taskseries_id(self) -> None:
        """Live: series 237677328 "Weekly GTD review", 17 occurrences, one stable series id."""
        assert entity_handle(
            task_id="1219062151", taskseries_id="237677328", repeat_kind="every"
        ) == ("237677328", True)

    def test_an_after_occurrence_is_its_own_task_id_and_is_NOT_recurring(self) -> None:
        """Paul, 2026-08-03: an `after` occurrence is an independent one-off, not a recurrence.

        RTM mints a new taskseries per `after` occurrence sharing only a name — its own docs say
        such a task "isn't tied to previous tasks" — so its `task_id` is a perfectly good durable
        handle and there is no refusal case. Live example: series 600211106.
        """
        assert entity_handle(
            task_id="1219999999", taskseries_id="600211106", repeat_kind="after"
        ) == ("1219999999", False)

    def test_an_unclassifiable_rule_is_not_treated_as_recurring(self) -> None:
        """The fourth `repeat_kind` case. Only "every" earns a series handle — nothing weaker."""
        assert entity_handle(task_id="900", taskseries_id="90", repeat_kind=None) == ("900", False)
        assert entity_handle(task_id="900", taskseries_id="90", repeat_kind="") == ("900", False)

    def test_entity_id_is_never_absent(self) -> None:
        """The guarantee the vault depends on: a non-empty string in every case, never null.

        A consumer never has to interpret an absent handle, which is why the refusal case the
        first draft of this design carried was dropped.
        """
        for kind in ("every", "after", None, "nonsense"):
            for series in ("77", "", None):
                eid, _ = entity_handle(task_id="1234", taskseries_id=series, repeat_kind=kind)
                assert isinstance(eid, str) and eid, (kind, series)

    def test_recurring_is_a_real_bool_never_a_truthy_string(self) -> None:
        """The vault's path builder rejects a non-bool — a truthy "false" picks the wrong shape."""
        for kind in ("every", "after", None):
            _, recurring = entity_handle(task_id="1", taskseries_id="2", repeat_kind=kind)
            assert recurring is True or recurring is False

    def test_recurring_is_true_iff_entity_id_is_the_series_id(self) -> None:
        """The invariant the degradation guard buys: the pair can never disagree.

        `recurring=True` alongside a task_id would be the silent-wrong-identity failure — a
        caller keying durable state on an id that re-keys per occurrence, with nothing saying so.
        """
        for kind in ("every", "after", None):
            for series in ("237677328", ""):
                eid, recurring = entity_handle(
                    task_id="1219062151", taskseries_id=series, repeat_kind=kind
                )
                assert recurring == (eid == series and bool(series))

    def test_an_every_with_no_series_id_degrades_to_not_recurring(self) -> None:
        """Structurally unreachable (the rrule hangs on the very series whose id this is), but
        the direction is chosen deliberately. `recurring=False` on a truly recurring item costs
        a folder per occurrence — ugly and recoverable. `recurring=True` on a re-keying id is
        the failure this field exists to prevent."""
        assert entity_handle(task_id="1219062151", taskseries_id="", repeat_kind="every") == (
            "1219062151",
            False,
        )

    def test_it_is_never_re_derived_from_the_presence_of_an_id(self) -> None:
        """Every task has a taskseries_id, so `recurring = bool(taskseries_id)` would be True for
        the entire account. `repeat_kind` is the discriminator; the id presence is only a guard."""
        _, recurring = entity_handle(task_id="1", taskseries_id="99999", repeat_kind=None)
        assert recurring is False


class TestParseTasksResponse:
    """Test task response parsing."""

    def test_parse_single_task(self, sample_task_response: dict) -> None:
        """Test parsing single task."""
        tasks = parse_tasks_response(sample_task_response)

        assert len(tasks) == 1
        task = tasks[0]

        assert task["id"] == "789"
        assert task["taskseries_id"] == "456"
        assert task["list_id"] == "123"
        assert task["name"] == "Test Task"
        assert task["priority"] == "1"
        assert task["tags"] == ["work", "urgent"]
        # A one-off series (no rrule) reads is_repeating False.
        assert task["is_repeating"] is False

    def test_parse_is_repeating_from_rrule(self) -> None:
        """A taskseries with an `rrule` element marks every occurrence's task is_repeating."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": [
                    {
                        "id": "1",
                        "taskseries": {
                            "id": "10",
                            "name": "Weekly review",
                            "tags": [],
                            "notes": [],
                            "rrule": {"every": "1", "$t": "FREQ=WEEKLY;INTERVAL=1"},
                            "task": {"id": "100", "priority": "N"},
                        },
                    },
                    {
                        "id": "2",
                        "taskseries": {
                            "id": "20",
                            "name": "One-off",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "200", "priority": "N"},
                        },
                    },
                ]
            },
        }
        tasks = parse_tasks_response(result)
        assert tasks[0]["is_repeating"] is True
        assert tasks[1]["is_repeating"] is False

    def test_parse_repeat_kind_travels_with_is_repeating(self) -> None:
        """The parsed task carries the recurrence KIND, not only that one exists.

        Both live shapes, taken verbatim from the 2026-08-03 account census: `every="1"` is an
        every-type repeat (one series, many tasks, stable taskseries_id) and `every="0"` an
        after-type (a new series per occurrence, both ids re-keyed).
        """
        result = {
            "stat": "ok",
            "tasks": {
                "list": [
                    {
                        "id": "1",
                        "taskseries": [
                            {
                                "id": "10",
                                "name": "Weekly GTD review",
                                "tags": [],
                                "notes": [],
                                "rrule": {"every": "1", "$t": "FREQ=WEEKLY;INTERVAL=1;WKST=MO"},
                                "task": {"id": "100", "priority": "N"},
                            },
                            {
                                "id": "20",
                                "name": "z4 car insurance",
                                "tags": [],
                                "notes": [],
                                "rrule": {"every": "0", "$t": "FREQ=YEARLY;INTERVAL=1;WKST=MO"},
                                "task": {"id": "200", "priority": "N"},
                            },
                            {
                                "id": "30",
                                "name": "One-off",
                                "tags": [],
                                "notes": [],
                                "task": {"id": "300", "priority": "N"},
                            },
                        ],
                    }
                ]
            },
        }
        by_id = {t["id"]: t for t in parse_tasks_response(result)}

        assert by_id["100"]["repeat_kind"] == "every"
        assert by_id["200"]["repeat_kind"] == "after"
        # Not repeating at all — kind is None, and `is_repeating` is what says which None this is.
        assert by_id["300"]["repeat_kind"] is None
        assert by_id["300"]["is_repeating"] is False

    def test_parse_empty_response(self) -> None:
        """Test parsing empty response."""
        result = {"stat": "ok", "tasks": {}}
        tasks = parse_tasks_response(result)

        assert tasks == []

    def test_parse_multiple_lists(self) -> None:
        """Test parsing tasks from multiple lists."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": [
                    {
                        "id": "1",
                        "taskseries": {
                            "id": "10",
                            "name": "Task 1",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "100", "priority": "N"},
                        },
                    },
                    {
                        "id": "2",
                        "taskseries": {
                            "id": "20",
                            "name": "Task 2",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "200", "priority": "2"},
                        },
                    },
                ]
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 2
        assert tasks[0]["list_id"] == "1"
        assert tasks[1]["list_id"] == "2"

    def test_parse_write_response_format(self) -> None:
        """Test parsing write operation response (list at top level, not under tasks)."""
        result = {
            "stat": "ok",
            "transaction": {"id": "12345", "undoable": "1"},
            "list": {
                "id": "1",
                "taskseries": {
                    "id": "10",
                    "name": "Created Task",
                    "parent_task_id": "100",
                    "tags": {"tag": "test"},
                    "notes": [],
                    "task": {"id": "200", "priority": "N"},
                },
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 1
        assert tasks[0]["name"] == "Created Task"
        assert tasks[0]["parent_task_id"] == "100"
        assert tasks[0]["list_id"] == "1"

    def test_parse_parent_task_id_empty_string(self) -> None:
        """Test that empty parent_task_id (top-level task) is normalised to None."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": {
                    "id": "1",
                    "taskseries": {
                        "id": "10",
                        "name": "Top Level Task",
                        "parent_task_id": "",
                        "tags": [],
                        "notes": [],
                        "task": {"id": "100", "priority": "N"},
                    },
                }
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 1
        assert tasks[0]["parent_task_id"] is None

    def test_parse_parent_task_id_populated(self) -> None:
        """Test that a populated parent_task_id is preserved."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": {
                    "id": "1",
                    "taskseries": {
                        "id": "20",
                        "name": "Child Task",
                        "parent_task_id": "100",
                        "tags": [],
                        "notes": [],
                        "task": {"id": "200", "priority": "N"},
                    },
                }
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 1
        assert tasks[0]["parent_task_id"] == "100"

    def test_parse_parent_task_id_absent(self) -> None:
        """Test that missing parent_task_id key defaults to None."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": {
                    "id": "1",
                    "taskseries": {
                        "id": "30",
                        "name": "Legacy Task",
                        "tags": [],
                        "notes": [],
                        "task": {"id": "300", "priority": "N"},
                    },
                }
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 1
        assert tasks[0]["parent_task_id"] is None

    def test_parse_parent_and_subtasks_as_siblings(self) -> None:
        """Test that parent and subtasks in the same list are all parsed with correct parent_task_id."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": {
                    "id": "1",
                    "taskseries": [
                        {
                            "id": "10",
                            "name": "Parent Project",
                            "parent_task_id": "",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "100", "priority": "1"},
                        },
                        {
                            "id": "20",
                            "name": "Child Alpha",
                            "parent_task_id": "100",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "200", "priority": "N"},
                        },
                        {
                            "id": "30",
                            "name": "Child Beta",
                            "parent_task_id": "100",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "300", "priority": "N"},
                        },
                    ],
                }
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 3

        parent = next(t for t in tasks if t["name"] == "Parent Project")
        alpha = next(t for t in tasks if t["name"] == "Child Alpha")
        beta = next(t for t in tasks if t["name"] == "Child Beta")

        assert parent["parent_task_id"] is None
        assert alpha["parent_task_id"] == "100"
        assert beta["parent_task_id"] == "100"

    def test_parse_subtasks_across_different_lists(self) -> None:
        """Test subtasks that ended up in different lists than the parent."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": [
                    {
                        "id": "1",
                        "taskseries": {
                            "id": "10",
                            "name": "Parent Task",
                            "parent_task_id": "",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "100", "priority": "1"},
                        },
                    },
                    {
                        "id": "2",
                        "taskseries": {
                            "id": "20",
                            "name": "Child In Other List",
                            "parent_task_id": "100",
                            "tags": [],
                            "notes": [],
                            "task": {"id": "200", "priority": "N"},
                        },
                    },
                ]
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 2
        parent = next(t for t in tasks if t["name"] == "Parent Task")
        child = next(t for t in tasks if t["name"] == "Child In Other List")
        assert parent["list_id"] == "1"
        assert child["list_id"] == "2"
        assert child["parent_task_id"] == "100"

    def test_parse_recurring_task_multiple_instances(self) -> None:
        """Test recurring task with multiple task elements in one taskseries."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": {
                    "id": "1",
                    "taskseries": {
                        "id": "10",
                        "name": "Weekly Review",
                        "parent_task_id": "",
                        "tags": {"tag": "recurring"},
                        "notes": [],
                        "task": [
                            {
                                "id": "100",
                                "due": "2026-03-31T00:00:00Z",
                                "priority": "N",
                                "completed": "2026-03-31T10:00:00Z",
                            },
                            {
                                "id": "101",
                                "due": "2026-04-07T00:00:00Z",
                                "priority": "N",
                                "completed": "",
                            },
                        ],
                    },
                }
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 2
        assert tasks[0]["id"] == "100"
        assert tasks[1]["id"] == "101"
        # Both share the same taskseries metadata
        assert tasks[0]["taskseries_id"] == "10"
        assert tasks[1]["taskseries_id"] == "10"
        assert tasks[0]["name"] == "Weekly Review"
        assert tasks[1]["name"] == "Weekly Review"
        assert tasks[0]["tags"] == ["recurring"]

    def test_parse_subtask_with_full_metadata(self) -> None:
        """Test that subtasks preserve all metadata fields identically to top-level tasks."""
        result = {
            "stat": "ok",
            "tasks": {
                "list": {
                    "id": "1",
                    "taskseries": {
                        "id": "20",
                        "name": "Child With Metadata",
                        "parent_task_id": "100",
                        "url": "https://example.com",
                        "location_id": "loc123",
                        "created": "2026-03-29T11:00:00Z",
                        "modified": "2026-03-30T09:00:00Z",
                        "tags": {"tag": ["action", "urgent"]},
                        "notes": {"note": {"id": "n1", "title": "Note", "$t": "Details"}},
                        "task": {
                            "id": "200",
                            "due": "2026-04-10T00:00:00Z",
                            "has_due_time": "1",
                            "start": "2026-04-05T00:00:00Z",
                            "has_start_time": "0",
                            "completed": "",
                            "deleted": "",
                            "priority": "1",
                            "postponed": "2",
                            "estimate": "PT2H",
                        },
                    },
                }
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 1
        t = tasks[0]
        assert t["parent_task_id"] == "100"
        assert t["name"] == "Child With Metadata"
        assert t["priority"] == "1"
        assert t["due"] == "2026-04-10T00:00:00Z"
        assert t["has_due_time"] is True
        assert t["start"] == "2026-04-05T00:00:00Z"
        assert t["estimate"] == "PT2H"
        assert t["postponed"] == 2
        assert t["tags"] == ["action", "urgent"]
        assert len(t["notes"]) == 1
        assert t["url"] == "https://example.com"
        assert t["location_id"] == "loc123"

    def test_parse_write_response_empty_list(self) -> None:
        """Test write response with no taskseries (edge case)."""
        result = {
            "stat": "ok",
            "transaction": {"id": "12345", "undoable": "1"},
            "list": {"id": "1"},
        }

        tasks = parse_tasks_response(result)
        assert tasks == []

    def test_parse_write_response_cleared_parent(self) -> None:
        """Test set_parent_task response where parent was cleared (promoted to top-level)."""
        result = {
            "stat": "ok",
            "transaction": {"id": "12345", "undoable": "1"},
            "list": {
                "id": "1",
                "taskseries": {
                    "id": "20",
                    "name": "Promoted Task",
                    "parent_task_id": "",
                    "tags": [],
                    "notes": [],
                    "task": {"id": "200", "priority": "N"},
                },
            },
        }

        tasks = parse_tasks_response(result)
        assert len(tasks) == 1
        assert tasks[0]["parent_task_id"] is None


class TestParseListsResponse:
    """Test list response parsing."""

    def test_parse_lists(self, sample_lists_response: dict) -> None:
        """Test parsing lists."""
        lists = parse_lists_response(sample_lists_response)

        assert len(lists) == 3
        assert lists[0]["name"] == "Inbox"
        assert lists[0]["locked"] is True
        assert lists[1]["name"] == "Personal"
        assert lists[2]["name"] == "Work"

    def test_parse_single_list(self) -> None:
        """Test parsing single list (dict instead of list)."""
        result = {
            "stat": "ok",
            "lists": {
                "list": {
                    "id": "1",
                    "name": "Only List",
                    "deleted": "0",
                    "locked": "0",
                    "archived": "0",
                    "position": "0",
                    "smart": "0",
                }
            },
        }

        lists = parse_lists_response(result)
        assert len(lists) == 1
        assert lists[0]["name"] == "Only List"


class TestFormatTask:
    """Test task formatting."""

    def test_format_basic_task(self) -> None:
        """Test basic task formatting."""
        task = {
            "id": "123",
            "taskseries_id": "456",
            "list_id": "789",
            "name": "Test Task",
            "priority": "1",
            "due": "2024-01-15T00:00:00Z",
            "completed": None,
            "tags": ["work"],
            "url": None,
            "notes": [],
        }

        formatted = format_task(task)

        assert formatted["name"] == "Test Task"
        assert formatted["priority"] == "high"
        assert formatted["id"] == "123"

    def test_format_task_carries_the_recurrence_pair(self) -> None:
        """`list_tasks` surfaces BOTH recurrence fields, because neither is usable alone.

        `repeat_kind` alone is undecodable — its None covers both "not repeating" and "repeating,
        kind unreadable" — so this formatter, which carried neither before v6.8.0, gains both.
        """
        base = {"id": "1", "taskseries_id": "10", "list_id": "100", "name": "T", "notes": []}

        every = format_task({**base, "is_repeating": True, "repeat_kind": "every"})
        assert every["is_repeating"] is True
        assert every["repeat_kind"] == "every"

        after = format_task({**base, "is_repeating": True, "repeat_kind": "after"})
        assert after["repeat_kind"] == "after"

        # A rule that could not be classified: kind None but is_repeating still TRUE, which is
        # what separates it from a plain one-off. Collapsing these two is the failure mode.
        unknown = format_task({**base, "is_repeating": True, "repeat_kind": None})
        assert unknown["repeat_kind"] is None
        assert unknown["is_repeating"] is True

        one_off = format_task(base)
        assert one_off["is_repeating"] is False
        assert one_off["repeat_kind"] is None

    def test_format_task_carries_the_entity_handle(self) -> None:
        """The generic tier surfaces `entity_id`/`recurring` too, so the transition off it is free.

        The raw ids stay beside them — this tier IS the escape hatch and still speaks RTM. It is
        the `gtd_*` layer that wraps the mechanics away.
        """
        base = {"id": "1", "taskseries_id": "10", "list_id": "100", "name": "T", "notes": []}

        every = format_task({**base, "is_repeating": True, "repeat_kind": "every"})
        assert every["entity_id"] == "10"  # the stable series id
        assert every["recurring"] is True
        assert every["id"] == "1" and every["taskseries_id"] == "10"  # raw ids retained

        after = format_task({**base, "is_repeating": True, "repeat_kind": "after"})
        assert after["entity_id"] == "1"  # its own task id — an independent one-off
        assert after["recurring"] is False

        # An unreadable rule must not be promoted to a series handle.
        unknown = format_task({**base, "is_repeating": True, "repeat_kind": None})
        assert unknown["entity_id"] == "1"
        assert unknown["recurring"] is False

        one_off = format_task(base)
        assert one_off["entity_id"] == "1"
        assert one_off["recurring"] is False

    def test_format_task_subtask_count(self) -> None:
        """Test that subtask_count is included in formatted output."""
        task = {
            "id": "100",
            "taskseries_id": "10",
            "list_id": "1",
            "name": "Parent Task",
            "priority": "N",
            "due": None,
            "completed": None,
            "tags": [],
            "url": None,
            "notes": [],
            "subtask_count": 3,
        }

        formatted = format_task(task)
        assert formatted["subtask_count"] == 3

    def test_format_task_subtask_count_default(self) -> None:
        """Test that subtask_count defaults to 0."""
        task = {
            "id": "100",
            "taskseries_id": "10",
            "list_id": "1",
            "name": "Task",
            "priority": "N",
            "due": None,
            "completed": None,
            "tags": [],
            "url": None,
            "notes": [],
        }

        formatted = format_task(task)
        assert formatted["subtask_count"] == 0

    def test_format_task_with_parent_task_id(self) -> None:
        """Test that parent_task_id is included in formatted output."""
        task = {
            "id": "200",
            "taskseries_id": "20",
            "list_id": "1",
            "name": "Child Task",
            "priority": "N",
            "due": None,
            "completed": None,
            "tags": [],
            "url": None,
            "notes": [],
            "parent_task_id": "100",
        }

        formatted = format_task(task)
        assert formatted["parent_task_id"] == "100"

    def test_format_task_without_parent_task_id(self) -> None:
        """Test that parent_task_id is None for top-level tasks."""
        task = {
            "id": "100",
            "taskseries_id": "10",
            "list_id": "1",
            "name": "Top Level Task",
            "priority": "N",
            "due": None,
            "completed": None,
            "tags": [],
            "url": None,
            "notes": [],
        }

        formatted = format_task(task)
        assert formatted["parent_task_id"] is None

    def test_format_mid_level_task(self) -> None:
        """Test a task that is both a child and a parent (mid-level in hierarchy)."""
        task = {
            "id": "200",
            "taskseries_id": "20",
            "list_id": "1",
            "name": "Mid-Level Task",
            "priority": "2",
            "due": None,
            "completed": None,
            "tags": ["project"],
            "url": None,
            "notes": [],
            "parent_task_id": "100",
            "subtask_count": 3,
        }

        formatted = format_task(task)
        assert formatted["parent_task_id"] == "100"
        assert formatted["subtask_count"] == 3

    def test_format_without_ids(self) -> None:
        """Test formatting without IDs."""
        task = {
            "id": "123",
            "taskseries_id": "456",
            "list_id": "789",
            "name": "Test",
            "priority": "N",
            "due": None,
            "completed": None,
            "tags": [],
            "url": None,
            "notes": [],
        }

        formatted = format_task(task, include_ids=False)

        assert "id" not in formatted
        assert "taskseries_id" not in formatted


class TestFormatList:
    """Test list formatting."""

    def test_format_list(self) -> None:
        """Test list formatting from raw RTM strings (write-response path)."""
        lst = {
            "id": "123",
            "name": "Test List",
            "smart": "0",
            "archived": "0",
            "locked": "1",
        }

        formatted = format_list(lst)

        assert formatted["id"] == "123"
        assert formatted["name"] == "Test List"
        assert formatted["smart"] is False
        assert formatted["locked"] is True

    def test_format_list_raw_smart_string(self) -> None:
        """Raw RTM smart='1' string is surfaced as True (write-response path)."""
        formatted = format_list(
            {"id": "9", "name": "Due Today", "smart": "1", "archived": "0", "locked": "0"},
        )
        assert formatted["smart"] is True

    def test_format_list_parsed_booleans(self) -> None:
        """Already-parsed booleans (get_lists path) must survive formatting.

        Regression for the double-conversion bug where format_list re-checked
        ``== "1"`` against an already-parsed bool, yielding False for every flag.
        """
        formatted = format_list(
            {"id": "9", "name": "Due Today", "smart": True, "archived": True, "locked": True},
        )
        assert formatted["smart"] is True
        assert formatted["archived"] is True
        assert formatted["locked"] is True
