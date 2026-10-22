"""Offline regressions for the release upgrade harness (specs#97)."""

from __future__ import annotations

import argparse
import importlib.util
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

_spec = importlib.util.spec_from_file_location(
    "release_upgrade_acceptance",
    Path(__file__).with_name("release-upgrade-acceptance.py"),
)
upgrade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(upgrade)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("SCHEMA_VERSION = 37\n", 37),
        ("SCHEMA_VERSION: int = 43\n", 43),
        ('raise RuntimeError("must not import")\nSCHEMA_VERSION = 52\n', 52),
    ],
)
def test_schema_version_reads_source_without_importing(tmp_path, source, expected):
    store = tmp_path / "store.py"
    store.write_text(source, encoding="utf-8")
    assert upgrade.source_schema_version(store) == expected


@pytest.mark.parametrize(
    "source",
    [
        "OLDEST_SCHEMA = 2\n",
        "SCHEMA_VERSION = True\n",
        "SCHEMA_VERSION = 0\n",
        'SCHEMA_VERSION = "43"\n',
        "SCHEMA_VERSION = compute_version()\n",
        "SCHEMA_VERSION = 37\nSCHEMA_VERSION = 43\n",
    ],
)
def test_schema_version_refuses_missing_or_ambiguous_definition(tmp_path, source):
    store = tmp_path / "store.py"
    store.write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError, match="SCHEMA_VERSION.*store.py"):
        upgrade.source_schema_version(store)


def installed_store(ctx, version, schema):
    source = (
        ctx.prefix
        / "apps/workbench/versions"
        / version
        / "venv/Lib/site-packages/eugene_plexus_workbench/store.py"
    )
    source.parent.mkdir(parents=True)
    source.write_text(f"SCHEMA_VERSION = {schema}\n", encoding="utf-8")
    return source


def test_expected_schema_uses_the_running_version_not_an_old_environment(tmp_path):
    ctx = upgrade.Install(tmp_path, 19000)
    installed_store(ctx, "from-pin", 37)
    installed_store(ctx, "to-pin", 43)
    assert ctx.expected_workbench_schema("from-pin") == 37
    assert ctx.expected_workbench_schema("to-pin") == 43
    with pytest.raises(FileNotFoundError):
        ctx.expected_workbench_schema("missing-pin")


def test_people_parser_reads_contract_envelope():
    person = {"id": "person-id", "name": "morgan"}
    assert upgrade.people_from_response(
        {"people": [person], "owner": {"id": "operator"}, "operatorName": "operator"}
    ) == [person]
    assert upgrade.people_from_response({"people": []}) == []


@pytest.mark.parametrize(
    "payload",
    [1, [], {}, {"people": 1}, {"people": None}, {"people": [{}]}],
)
def test_people_parser_names_malformed_response(payload):
    with pytest.raises(AssertionError, match="GET /v1/people"):
        upgrade.people_from_response(payload)


def test_collect_state_reads_note_lists_with_integer_section_metadata():
    note = {"id": "note-id", "text": upgrade.NOTE, "kind": "fact", "pinned": True}
    api = Mock()
    payloads = {
        "/api/chats/chat-id": {"chat": {"title": upgrade.TITLE}, "messages": []},
        "/api/memory": {
            "sections": {"always": [note], "other": [], "otherTotal": 0, "past": []}
        },
        "/api/documents": {"documents": []},
        "/api/me": {"sub": "operator"},
    }
    api.call.side_effect = lambda base, method, path, **kw: payloads[path]
    api.client.get.return_value = httpx.Response(200, text=upgrade.DOC_BODY)
    state = upgrade.collect_state(
        api, "http://workbench", {}, "chat-id", "note-id", "doc-id"
    )
    assert state["note"] == note


@pytest.mark.parametrize("backup_schema", [37, 36])
def test_verify_uses_source_schema_and_requires_backup_of_observed_from_schema(
    tmp_path, backup_schema
):
    ctx = upgrade.Install(tmp_path, 19000)
    installed_store(ctx, "to-pin", 43)
    db = ctx.prefix / "apps/workbench/data/workbench.sqlite3"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('schema', '43')")
    db.with_name(f"{db.name}.schema-{backup_schema}.bak").touch()
    pins = dict.fromkeys(upgrade.COMPONENTS, "a" * 40)
    state = {
        "chat": {"title": upgrade.TITLE, "messages": []},
        "note": {"id": "note-id"},
        "document": {"id": "doc-id"},
        "documentSha256": "doc-hash",
        "documentText": upgrade.DOC_BODY,
    }
    seeded = {
        "schema": 37,
        "personId": "person-id",
        "chatId": "chat-id",
        "noteId": "note-id",
        "docId": "doc-id",
        "operatorSub": "operator",
        "state": state,
        "reply": False,
    }
    payloads = {
        "/v1/app-catalogue": {
            "apps": [{"manifest": {"id": "workbench", "version": "to-pin"}}]
        },
        "/v1/auth/login": {"sessionToken": "token"},
        "/v1/people": {"people": [{"id": "person-id", "name": upgrade.SECOND["name"]}]},
        "/api/me": {"sub": "operator"},
    }
    api = Mock()
    api.call.side_effect = lambda base, method, path, *args, **kw: payloads[path]
    checks = []
    with (
        patch.object(ctx, "commits", return_value=pins),
        patch.object(
            upgrade,
            "workbench_up",
            return_value=({"version": "to-pin"}, "http://workbench"),
        ),
        patch.object(upgrade, "sign_in", return_value={}),
        patch.object(upgrade, "collect_state", return_value=state),
        patch.object(upgrade, "CHECKS", checks),
        patch.object(upgrade, "RESULT", {}),
        patch.object(upgrade, "say"),
    ):
        upgrade.verify(ctx, api, "token", seeded, {"components": pins}, {})
    failures = [c["name"] for c in checks if not c["passed"]]
    assert failures == (
        [] if backup_schema == 37 else ["TO: migration kept a schema-37 backup"]
    )


def test_windows_output_limit_is_checked_before_creating_files(tmp_path):
    output = tmp_path / ("deep-" * 25)
    with (
        patch.object(upgrade.sys, "platform", "win32"),
        patch.object(upgrade, "snapshot_live") as snapshot,
        pytest.raises(ValueError, match=r"--output.*80 characters.*Windows.*shorter"),
    ):
        upgrade.run(argparse.Namespace(output=output))
    assert not output.exists()
    snapshot.assert_not_called()


def test_windows_output_limit_boundary():
    for length in (80, 81):
        output = Path("C:/" + "a" * (length - 3))
        with patch.object(upgrade.sys, "platform", "win32"):
            if length == 80:
                upgrade.validate_output_path(output)
            else:
                with pytest.raises(ValueError, match="81 characters"):
                    upgrade.validate_output_path(output)


def test_output_limit_does_not_apply_to_other_platforms():
    with patch.object(upgrade.sys, "platform", "linux"):
        upgrade.validate_output_path(Path("/" + "deep/" * 50))
