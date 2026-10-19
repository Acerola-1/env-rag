"""Canonical CLI defaults must not revive the retired local account source."""

import subprocess
import sys
from pathlib import Path

import pytest

from env_rag_final.access.__main__ import resolve_mode


def test_canonical_cli_defaults_to_remote(monkeypatch):
    monkeypatch.delenv("ENV_RAG_AUTH_MODE", raising=False)
    assert resolve_mode() == "remote"
    assert resolve_mode("local") == "local"  # explicit isolated test support


@pytest.mark.parametrize(
    "name",
    [
        "wa_bootstrap_registry.py",
        "wa_third_workspace.py",
        "wa_lightrag_init_probe.py",
    ],
)
def test_retired_demo_entrypoints_refuse_before_work(name):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / name)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode != 0
    assert "退役" in result.stderr
