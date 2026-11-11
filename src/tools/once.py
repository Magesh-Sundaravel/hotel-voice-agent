"""Send-once emails that have no database row to mark (messages, follow-ups).

Keys are kept in memory, so a retry is caught within one running server, not
across a restart. Bounded, so a long-running server does not grow them forever.
A failed send forgets its key, so a later call can retry it.
"""

import logging
from collections import OrderedDict
from email.message import EmailMessage

from src.email.sender import EmailSender

logger = logging.getLogger(__name__)

_MAX_KEYS = 10_000
_seen: OrderedDict[str, None] = OrderedDict()


def first_time(key: str) -> bool:
    """Return True the first time a key is seen, False after that.

    Args:
        key: Identifies one send, e.g. "<call_id>|followup|<address>".

    Returns:
        Whether the caller should go ahead and send.
    """
    if key in _seen:
        return False
    _seen[key] = None
    if len(_seen) > _MAX_KEYS:
        _seen.popitem(last=False)
    return True


def forget(key: str) -> None:
    """Drop a key, so the next call with it sends again."""
    _seen.pop(key, None)


async def deliver(
    sender: EmailSender, message: EmailMessage, key: str, call_id: str, what: str
) -> None:
    """Send in the background; on failure, log the call_id only and forget the key.

    Args:
        sender: Sends the email.
        message: The email.
        key: Its send-once key, released if the send fails.
        call_id: For the log line; never any PII.
        what: What is being sent, for the log line.
    """
    try:
        await sender.send(message)
    except Exception as error:  # noqa: BLE001 - background job, nothing to raise to
        forget(key)
        logger.warning(
            "%s not sent for call %s: %s", what, call_id, type(error).__name__
        )
