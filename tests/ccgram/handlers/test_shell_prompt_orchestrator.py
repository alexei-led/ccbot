from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ccgram.handlers.shell_prompt_orchestrator import (
    _state,
    accept_offer,
    clear_state,
    ensure_setup,
    record_skip,
)

WINDOW = "@99"


@pytest.fixture(autouse=True)
def _clean_state():
    _state.clear()
    yield
    _state.clear()


@pytest.fixture()
def mock_setup():
    with patch(
        "ccgram.providers.shell_infra.setup_shell_prompt",
        new_callable=AsyncMock,
    ) as m:
        yield m


@pytest.fixture()
def mock_has_marker():
    with patch(
        "ccgram.providers.shell_infra.has_prompt_marker",
        new_callable=AsyncMock,
    ) as m:
        yield m


@pytest.mark.parametrize(
    "scenario, trigger, marker_present, skip_flag, expect_setup_call, expect_clear_arg",
    [
        ("auto_always_runs", "auto", False, False, True, True),
        ("auto_runs_even_with_marker", "auto", True, False, True, True),
        ("lazy_no_op_when_marker_present", "lazy", True, False, False, None),
        ("lazy_runs_when_marker_missing", "lazy", False, False, True, False),
        ("lazy_respects_skip_flag", "lazy", False, True, False, None),
        ("external_bind_shows_offer", "external_bind", False, False, True, False),
        (
            "external_bind_no_offer_if_marker_present",
            "external_bind",
            True,
            False,
            False,
            None,
        ),
        (
            "provider_switch_reoffers_after_skip_cleared",
            "provider_switch",
            False,
            False,
            True,
            False,
        ),
        ("provider_switch_respects_skip", "provider_switch", False, True, False, None),
    ],
    ids=lambda v: v if isinstance(v, str) and "_" in v else "",
)
async def test_ensure_setup_scenarios(
    scenario,
    trigger,
    marker_present,
    skip_flag,
    expect_setup_call,
    expect_clear_arg,
    mock_setup,
    mock_has_marker,
):
    mock_has_marker.return_value = marker_present
    if skip_flag:
        record_skip(WINDOW)

    await ensure_setup(WINDOW, trigger)

    if expect_setup_call:
        mock_setup.assert_awaited_once()
        _, kwargs = mock_setup.await_args
        assert kwargs["clear"] is expect_clear_arg
    else:
        mock_setup.assert_not_awaited()


async def test_accept_offer_runs_setup(mock_setup, mock_has_marker):
    await accept_offer(WINDOW)

    mock_setup.assert_awaited_once_with(WINDOW, clear=False)
    assert _state[WINDOW].was_offered is True


async def test_record_skip_sets_flag():
    record_skip(WINDOW)
    assert _state[WINDOW].skip_flag is True


async def test_clear_state_removes_entry():
    record_skip(WINDOW)
    assert WINDOW in _state
    clear_state(WINDOW)
    assert WINDOW not in _state


async def test_clear_state_no_op_for_unknown_window():
    clear_state("@unknown")
