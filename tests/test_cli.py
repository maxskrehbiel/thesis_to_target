"""Command-line interface: subcommands, exit codes, argument types and logging levels."""

from __future__ import annotations

import logging
import runpy
import sys
from pathlib import Path

import pytest

from thesis_to_target import __version__
from thesis_to_target.cli import main
from thesis_to_target.errors import LedgerError
from thesis_to_target.qa import CheckResult
from thesis_to_target.thesis import demo_thesis_text

DEMO_FILES = {
    "targets.csv",
    "targets.xlsx",
    "evidence_ledger.csv",
    "review_queue.csv",
    "raw_records.csv",
    "target_brief.md",
    "thesis.yaml",
}


@pytest.fixture
def thesis_file(tmp_path: Path) -> Path:
    path = tmp_path / "thesis.yaml"
    path.write_text(demo_thesis_text(), encoding="utf-8", newline="\n")
    return path


def test_validate(thesis_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "--thesis", str(thesis_file)]) == 0
    assert capsys.readouterr().out.startswith("ok: Commercial fire")


def test_demo_runs_from_any_directory_and_grades_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    written = {p.name for p in (tmp_path / "demo_output").iterdir()}
    assert written == DEMO_FILES
    assert (tmp_path / "demo_output" / "thesis.yaml").read_text(
        encoding="utf-8"
    ) == demo_thesis_text()
    assert "self-check against the synthetic ground truth:" in out
    assert out.count("PASS") == 5 and "FAIL" not in out


def test_demo_exits_1_when_its_self_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    failing = [CheckResult("resolution precision", 0.5, ">= 0.95", False)]
    monkeypatch.setattr("thesis_to_target.cli.check_report", lambda report: failing)
    assert main(["demo", "--out", str(tmp_path)]) == 1
    assert "FAIL  resolution precision" in capsys.readouterr().out


def test_run_writes_outputs(
    thesis_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "out"
    args = [
        "run",
        "--thesis",
        str(thesis_file),
        "--out",
        str(out_dir),
        "--seed",
        "7",
        "--n-firms",
        "30",
    ]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "data: synthetic (seed 7)" in out and "ledger:" in out
    assert (out_dir / "targets.csv").exists() and (out_dir / "target_brief.md").exists()
    assert not (out_dir / "thesis.yaml").exists()  # only the demo copies its thesis


def test_run_with_adjudications(thesis_file: Path, tmp_path: Path) -> None:
    sheet = tmp_path / "decisions.csv"
    sheet.write_text("record_a,record_b,decision\n", encoding="utf-8")
    args = [
        "run",
        "--thesis",
        str(thesis_file),
        "--out",
        str(tmp_path / "o"),
        "--adjudications",
        str(sheet),
    ]
    assert main(args) == 0


@pytest.mark.parametrize(
    "extra",
    [["--n-firms", "5"], ["--n-firms", "600"]],
    ids=["below the minimum", "above the generator's capacity"],
)
def test_config_errors_exit_2_with_one_clean_line(
    thesis_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    assert main(["run", "--thesis", str(thesis_file), "--out", str(tmp_path), *extra]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1 and "Traceback" not in err


def test_missing_thesis_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "--thesis", str(tmp_path / "missing.yaml")]) == 2
    assert "error: thesis file not found" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "-3", "many"])
def test_count_arguments_must_be_positive_integers(
    thesis_file: Path, tmp_path: Path, value: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--thesis", str(thesis_file), "--out", str(tmp_path), "--n-firms", value])
    assert exit_info.value.code == 2


def test_seed_may_be_zero_but_not_negative(thesis_file: Path, tmp_path: Path) -> None:
    assert main(["run", "--thesis", str(thesis_file), "--out", str(tmp_path), "--seed", "0"]) == 0
    with pytest.raises(SystemExit):
        main(["run", "--thesis", str(thesis_file), "--out", str(tmp_path), "--seed", "-1"])


def test_ledger_failure_exits_1(
    thesis_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise LedgerError("evidence ledger failed verification")

    monkeypatch.setattr("thesis_to_target.cli.run_pipeline", fail)
    assert main(["run", "--thesis", str(thesis_file), "--out", str(tmp_path)]) == 1


@pytest.mark.parametrize(
    ("flags", "level"), [([], logging.WARNING), (["-v"], logging.INFO), (["-vv"], logging.DEBUG)]
)
def test_verbosity_sets_the_log_level(
    thesis_file: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str], level: int
) -> None:
    seen: list[int] = []
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: seen.append(kwargs["level"]))
    assert main([*flags, "validate", "--thesis", str(thesis_file)]) == 0
    assert seen == [level]


def test_module_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["thesis_to_target", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("thesis_to_target", run_name="__main__")
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out
