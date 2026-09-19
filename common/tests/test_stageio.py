"""Tests for the stage output contract: emit_result / parse_result.

The contract exists because DockerOperator merges a container's stdout and
stderr, and the daemon does not guarantee their relative order when two writes
land microseconds apart on different pipes. These tests pin down both the
happy path and the race that motivated the sentinel-line design.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml_common.stageio import RESULT_PREFIX, emit_result, parse_result


def test_emit_result_prints_one_stdout_line_with_prefix(capsys):
    emit_result({"row_count": 800})

    captured = capsys.readouterr()
    lines = captured.out.splitlines()

    assert len(lines) == 1
    assert lines[0].startswith(RESULT_PREFIX)
    assert captured.err == ""


def test_emit_result_then_parse_result_round_trips(capsys):
    payload = {"fingerprint": "abc123", "row_count": 800, "ok": True}

    emit_result(payload)
    captured = capsys.readouterr()

    result = parse_result(captured.out.splitlines())

    assert result == payload


def test_parse_result_finds_result_line_when_not_last():
    lines = [
        f"{RESULT_PREFIX}{json.dumps({'row_count': 800})}",
        "some log line that arrived after the result on the merged stream",
        "another late log line",
    ]

    result = parse_result(lines)

    assert result == {"row_count": 800}


def test_parse_result_ignores_log_lines_that_look_like_json():
    lines = ["800", "wrote 800 rows", "1500"]

    with pytest.raises(ValueError):
        parse_result(lines)


def test_parse_result_raises_value_error_when_no_result_line():
    lines = ["just some log output", "nothing marked as a result"]

    with pytest.raises(ValueError):
        parse_result(lines)


def test_emit_result_raises_type_error_for_non_dict_payload():
    with pytest.raises(TypeError):
        emit_result([1, 2, 3])


def test_dag_file_repeats_result_prefix_literal():
    dag_path = Path(__file__).resolve().parents[2] / "dags" / "ml_pipeline_dag.py"
    if not dag_path.exists():
        pytest.skip("DAG file not present in this environment")

    dag_source = dag_path.read_text(encoding="utf-8")

    assert RESULT_PREFIX in dag_source
