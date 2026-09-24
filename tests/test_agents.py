"""The reviewer is launched in plan mode as a session, so its tool list must let it leave plan mode and register."""

from __future__ import annotations

from pathlib import Path

REVIEWER = Path(__file__).resolve().parent.parent / "agents" / "reviewer.md"


def test_reviewer_can_leave_plan_mode_and_register() -> None:
    # reviewer-COpusH-01, 2026-09-24 03:38–03:44: launched with --permission-mode plan, "ExitPlanMode is disabled for this session".
    front = REVIEWER.read_text().split("---")[1]
    line = next(l for l in front.splitlines() if l.startswith("tools:"))
    tools = {t.strip() for t in line.removeprefix("tools:").split(",")}
    assert {"EnterPlanMode", "ExitPlanMode", "ListAgents", "SendMessage"} <= tools
