"""
Tests for the llm-ssh-agent user unit.

The agent starts empty, and readiness still fails loudly.
"""

from pathlib import Path

import pytest

UNIT = (
    Path(__file__).resolve().parent.parent
    / "dotfiles/.config/systemd/user/llm-ssh-agent.service"
)


@pytest.fixture
def unit_lines() -> list[str]:
    """
    Read the unit file.

    :return: The unit's lines.
    """
    return UNIT.read_text().splitlines()


def test_exec_start_post_only_waits_for_socket(unit_lines):
    post_lines = [line for line in unit_lines if line.startswith("ExecStartPost=")]

    assert len(post_lines) == 1
    assert '[ -S "$$SSH_AUTH_SOCK" ]' in post_lines[0]
    assert "exit 1" in post_lines[0]


def test_unit_never_loads_a_key(unit_lines):
    assert [line for line in unit_lines if "ssh-add" in line] == []


def test_askpass_stays_disabled(unit_lines):
    assert "Environment=SSH_ASKPASS_REQUIRE=never" in unit_lines
