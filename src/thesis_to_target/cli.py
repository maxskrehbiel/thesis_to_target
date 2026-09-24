"""Command-line interface: ``thesis_to_target run | demo | validate``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .brief import write_brief
from .errors import LedgerError, ThesisToTargetError
from .export import export_run
from .pipeline import RunResult, load_adjudications, run_pipeline
from .qa import CheckResult, check_report
from .registry import build_adapters, build_presence_checkers
from .thesis import Thesis, demo_thesis_text, load_demo_thesis, load_thesis

DEMO_OUTPUT = Path("demo_output")
EXIT_OK = 0
EXIT_CHECK_FAILED = 1  # ledger verification or the demo's self-check failed
EXIT_USAGE = 2  # usage, configuration or input error
_LOG_LEVELS = (logging.WARNING, logging.INFO, logging.DEBUG)


def positive_int(text: str) -> int:
    """Argparse type for an integer of at least 1."""
    value = _integer(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return value


def non_negative_int(text: str) -> int:
    """Argparse type for an integer of at least 0."""
    value = _integer(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be zero or a positive integer, got {value}")
    return value


def _integer(text: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with its three subcommands."""
    parser = argparse.ArgumentParser(
        prog="thesis_to_target",
        description="Turn an investment thesis into a ranked, evidence-backed target list.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="-v for progress, -vv for debug detail"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a thesis and write its outputs")
    run.add_argument("--thesis", required=True, type=Path, help="thesis YAML file")
    run.add_argument("--out", required=True, type=Path, help="output directory")
    run.add_argument("--seed", type=non_negative_int, help="override the synthetic seed")
    run.add_argument(
        "--n-firms", type=positive_int, help="override the number of synthetic base firms"
    )
    run.add_argument("--adjudications", type=Path, help="review-queue CSV with filled-in decisions")

    demo = sub.add_parser(
        "demo", help="run the bundled synthetic demo and grade it against its truth"
    )
    demo.add_argument(
        "--out", type=Path, default=DEMO_OUTPUT, help=f"output directory (default: {DEMO_OUTPUT})"
    )

    validate = sub.add_parser("validate", help="check a thesis file without running it")
    validate.add_argument("--thesis", required=True, type=Path, help="thesis YAML file")
    return parser


def _display(path: Path) -> str:
    """Show a path relative to the working directory, or just its name if it lies outside."""
    cwd, full = Path.cwd().resolve(), path.resolve()
    return full.relative_to(cwd).as_posix() if full.is_relative_to(cwd) else full.name


def _execute(
    thesis: Thesis, out_dir: Path, adjudications: Path | None
) -> tuple[RunResult, list[Path]]:
    decisions = load_adjudications(adjudications) if adjudications else None
    result = run_pipeline(
        thesis, build_adapters(thesis), build_presence_checkers(thesis), decisions
    )
    written = [*export_run(result, out_dir).values(), write_brief(result, out_dir)]
    return result, written


def _summarize(result: RunResult, written: Sequence[Path]) -> None:
    t = result.thesis
    print(f"thesis: {t.name}")
    print(
        f"data: synthetic (seed {t.synthetic.seed})"
        if result.synthetic
        else "data: configured sources"
    )
    for key, value in asdict(result.funnel).items():
        if key != "records_by_feed":
            print(f"  {key:<16} {value}")
    print(f"ledger: {len(result.ledger)} claims, verified")
    print("wrote:")
    for path in sorted(written):
        print(f"  {_display(path)}")


def _print_checks(checks: Sequence[CheckResult]) -> None:
    print("self-check against the synthetic ground truth:")
    for c in checks:
        value = "n/a" if c.value is None else f"{c.value:.3f}"
        print(
            f"  {'PASS' if c.passed else 'FAIL'}  {c.name:<28} {value:>7}  (needs {c.requirement})"
        )


def _demo(out_dir: Path) -> int:
    result, written = _execute(load_demo_thesis(), out_dir, None)
    thesis_copy = out_dir / "thesis.yaml"
    thesis_copy.write_text(demo_thesis_text(), encoding="utf-8", newline="\n")
    _summarize(result, [*written, thesis_copy])
    if result.qa is None:
        print("self-check: no ground truth available", file=sys.stderr)
        return EXIT_CHECK_FAILED
    checks = check_report(result.qa)
    _print_checks(checks)
    return EXIT_OK if all(c.passed for c in checks) else EXIT_CHECK_FAILED


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "validate":
        thesis = load_thesis(args.thesis)
        print(f"ok: {thesis.name} ({len(thesis.sources)} sources, {len(thesis.states)} states)")
        return EXIT_OK
    if args.command == "demo":
        return _demo(args.out)
    thesis = load_thesis(args.thesis).with_synthetic(seed=args.seed, n_firms=args.n_firms)
    result, written = _execute(thesis, args.out, args.adjudications)
    _summarize(result, written)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code: 0 success, 1 a verification or self-check failed, 2 usage,
        configuration or input error.
    """
    args = build_parser().parse_args(argv)
    level = _LOG_LEVELS[min(args.verbose, len(_LOG_LEVELS) - 1)]
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    try:
        return _dispatch(args)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CHECK_FAILED
    except ThesisToTargetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
