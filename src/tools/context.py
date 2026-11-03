"""The call facts tools need but the model must never generate."""

from pydantic import BaseModel


class CallContext(BaseModel):
    """Bound when the registry is built; never part of a tool's parameters.

    The CLI makes a random call_id and takes --caller-phone, each eval case sets
    its own, and the ElevenLabs webhook fills it from the call (step 1).
    """

    call_id: str
    caller_phone: str | None = None
