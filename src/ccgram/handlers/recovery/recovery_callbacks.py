"""Recovery callback dispatcher + shared validators.

After the Round 5 split, this module is a thin dispatcher: it routes
prefix-tagged callback data to the banner handlers in
:mod:`recovery_banner` or the picker handler in :mod:`resume_picker`,
and owns the two validators (``_validate_recovery_state``,
``_clear_recovery_state``) used by both flows.

Why the validators live here: both sibling modules need them, and putting
them in either one would create a redundant cycle. Keeping them on the
dispatcher (which has no top-level imports of the siblings) means
``recovery_banner`` and ``resume_picker`` can both import the validators
eagerly, while the dispatcher imports the handler modules lazily inside
``handle_recovery_callback`` to break the cycle.

Routes handled:
  - CB_RECOVERY_FRESH: create fresh session in same directory
  - CB_RECOVERY_CONTINUE: continue most recent session
  - CB_RECOVERY_RESUME: show session picker
  - CB_RECOVERY_PICK: a session was picked from the list
  - CB_RECOVERY_BACK: return from the picker to the banner
  - CB_RECOVERY_BROWSE: switch to the cross-project picker
  - CB_RECOVERY_CANCEL: dismiss the recovery flow
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from telegram import CallbackQuery, Update

from ...thread_router import thread_router
from ..callback_data import (
    CB_RECOVERY_BACK,
    CB_RECOVERY_BROWSE,
    CB_RECOVERY_CANCEL,
    CB_RECOVERY_CONTINUE,
    CB_RECOVERY_FRESH,
    CB_RECOVERY_PICK,
    CB_RECOVERY_RESUME,
)
from ..callback_helpers import get_thread_id
from ..callback_registry import register
from ..user_state import (
    PENDING_THREAD_ID,
    PENDING_THREAD_TEXT,
    RECOVERY_SESSIONS,
    RECOVERY_WINDOW_ID,
)

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logger = structlog.get_logger()


def _validate_recovery_state(
    data_suffix: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[int, str] | None:
    """Validate common recovery preconditions.

    Supports two paths:
      1. Text-handler path: PENDING_THREAD_ID and RECOVERY_WINDOW_ID in user_data.
      2. Proactive notification path: no user_data state, validate via binding.

    Returns ``(thread_id, old_window_id)`` on success, or ``None`` on
    failure (caller should return early and call ``query.answer``). The
    caller looks up ``cwd`` via :mod:`window_query` itself — keeping the
    validator window_query-free means the sibling-import cycle stays
    one-way and tests only need to patch the banner module.
    """
    thread_id = get_thread_id(update)
    if thread_id is None:
        return None

    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return None

    pending_tid = (
        context.user_data.get(PENDING_THREAD_ID) if context.user_data else None
    )
    stored_wid = (
        context.user_data.get(RECOVERY_WINDOW_ID) if context.user_data else None
    )

    if pending_tid is not None:
        if thread_id != pending_tid or stored_wid != data_suffix:
            return None
    else:
        bound_wid = thread_router.get_window_for_thread(user_id, thread_id)
        if bound_wid != data_suffix:
            return None
        if context.user_data is not None:
            context.user_data[PENDING_THREAD_ID] = thread_id
            context.user_data[RECOVERY_WINDOW_ID] = data_suffix

    return thread_id, data_suffix


def _clear_recovery_state(user_data: dict | None) -> None:
    """Remove all recovery-related keys from user_data."""
    if user_data is None:
        return
    for key in (
        PENDING_THREAD_ID,
        PENDING_THREAD_TEXT,
        RECOVERY_WINDOW_ID,
        RECOVERY_SESSIONS,
    ):
        user_data.pop(key, None)


async def handle_recovery_callback(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle recovery UI callbacks."""
    # Lazy: sibling cycle — recovery_banner / resume_picker import the
    # validators above, so importing them at module load would create a
    # cycle.
    # Lazy: dispatcher → handler-module cycle (siblings register on import)
    from .recovery_banner import (
        _handle_back,
        _handle_browse,
        _handle_cancel,
        _handle_continue,
        _handle_fresh,
        _handle_resume,
    )

    # Lazy: dispatcher → handler-module cycle (siblings register on import)
    from .resume_picker import _handle_resume_pick

    # Order matters: CB_RECOVERY_BROWSE ("rec:br:") shares its prefix with
    # CB_RECOVERY_BACK ("rec:b:"), so BROWSE must be tested first.
    if data.startswith(CB_RECOVERY_BROWSE):
        await _handle_browse(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_BACK):
        await _handle_back(query, data, update, context)
    elif data.startswith(CB_RECOVERY_FRESH):
        await _handle_fresh(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_CONTINUE):
        await _handle_continue(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_RESUME):
        await _handle_resume(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_PICK):
        await _handle_resume_pick(query, user_id, data, update, context)
    elif data == CB_RECOVERY_CANCEL:
        await _handle_cancel(query, update, context)


@register(
    CB_RECOVERY_BACK,
    CB_RECOVERY_BROWSE,
    CB_RECOVERY_FRESH,
    CB_RECOVERY_CONTINUE,
    CB_RECOVERY_RESUME,
    CB_RECOVERY_PICK,
    CB_RECOVERY_CANCEL,
)
async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    assert query is not None and query.data is not None and user is not None
    await handle_recovery_callback(query, user.id, query.data, update, context)
