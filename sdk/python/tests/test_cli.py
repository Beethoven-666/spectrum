"""Smoke tests for the argparse-based CLI."""

from __future__ import annotations

import pytest

from h1_sdk.cli import build_parser


def test_parser_help_smoke():
    parser = build_parser()
    # Each subcommand should parse with --port set.
    for sub in (
        ["info", "--port", "/tmp/x"],
        ["capture", "--port", "/tmp/x"],
        ["capture", "--port", "/tmp/x", "--tm30"],
        ["stream", "--port", "/tmp/x", "--count", "3"],
        ["stream", "--port", "/tmp/x", "--csv", "out.csv"],
        ["set-exposure", "100000", "--port", "/tmp/x"],
        ["get-exposure", "--port", "/tmp/x"],
        ["set-mode", "manual", "--port", "/tmp/x"],
        ["set-mode", "auto", "--port", "/tmp/x"],
        ["get-mode", "--port", "/tmp/x"],
        ["reset-curve", "--port", "/tmp/x"],
    ):
        ns = parser.parse_args(sub)
        assert ns.cmd == sub[0]
        assert ns.port == "/tmp/x"


def test_parser_rejects_unknown_subcommand():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["does-not-exist"])


def test_parser_requires_port():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["info"])


def test_parser_invalid_mode_choice():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["set-mode", "weird", "--port", "/tmp/x"])
