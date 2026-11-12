"""The message for reception (take_message) and the follow-up email to a caller."""

from email.message import EmailMessage
from typing import Literal

from src.email.compose import HOTEL_NAME

Topic = Literal["booking", "change", "cancellation", "information"]

_LANGUAGE_NAMES = {"it": "Italian", "en": "English"}

_TOPICS = {
    "en": {
        "booking": "your booking",
        "change": "the change to your booking",
        "cancellation": "the cancellation of your booking",
        "information": "your question",
    },
    "it": {
        "booking": "la sua prenotazione",
        "change": "la modifica della sua prenotazione",
        "cancellation": "la cancellazione della sua prenotazione",
        "information": "la sua richiesta di informazioni",
    },
}

_FOLLOWUP = {
    "en": {
        "subject": "{hotel}: we can help by email",
        "greeting": "Dear {first_name},",
        "greeting_no_name": "Dear guest,",
        "body": (
            "{greeting}\n\n"
            "thank you for calling {hotel}. We are sorry we could not finish "
            "{topic} on the phone.\n\n"
            "Please reply to this email with what you need, including the dates "
            "and your booking reference if you have one, and our reception team "
            "will take care of it.\n\n"
            "{hotel}\n"
            "Via della Lupa 12, Rome\n"
        ),
    },
    "it": {
        "subject": "{hotel}: possiamo aiutarla via email",
        "greeting": "Gentile {first_name},",
        "greeting_no_name": "Gentile ospite,",
        "body": (
            "{greeting}\n\n"
            "grazie per aver chiamato il {hotel}. Ci scusiamo per non essere "
            "riusciti a completare {topic} al telefono.\n\n"
            "Risponda a questa email indicando di cosa ha bisogno, con le date e il "
            "codice di prenotazione se ne ha uno, e il nostro ricevimento se ne "
            "occuperà.\n\n"
            "{hotel}\n"
            "Via della Lupa 12, Roma\n"
        ),
    },
}


def _one_line(text: str) -> str:
    """Collapse whitespace, so text from the model cannot break a header."""
    return " ".join(text.split())


def reception_message(
    *,
    hotel_inbox: str,
    first_name: str,
    last_name: str,
    message: str,
    language: Literal["it", "en"],
    phone: str | None,
    email: str | None,
    call_id: str,
) -> EmailMessage:
    """Build the email that passes a caller's message to reception.

    It goes to the hotel's own inbox. A caller email becomes the Reply-To, so staff
    can answer straight from it.

    Args:
        hotel_inbox: The hotel's address; both sender and recipient.
        first_name: The caller's first name.
        last_name: The caller's last name.
        message: The agent's summary of what the caller wants.
        language: The language of the call.
        phone: Where to reach the caller (E.164), if known.
        email: The caller's email, if given.
        call_id: The ElevenLabs conversation id, to find the call's trace.

    Returns:
        A plain-text email for reception.
    """
    name = _one_line(f"{first_name} {last_name}")
    msg = EmailMessage()
    msg["From"] = f"{HOTEL_NAME} phone receptionist <{hotel_inbox}>"
    msg["To"] = hotel_inbox
    msg["Subject"] = f"Phone message from {name}"
    if email:
        msg["Reply-To"] = email
    msg.set_content(
        f"Caller: {name}\n"
        f"Phone: {phone or 'not given'}\n"
        f"Email: {email or 'not given'}\n"
        f"Language: {_LANGUAGE_NAMES[language]}\n\n"
        f"Message:\n{message.strip()}\n\n"
        f"Call id: {call_id}\n\n"
        "Taken by the AI phone receptionist. The caller was told the message was "
        "passed to reception, with no promise of when or how we reply.\n"
    )
    return msg


def followup_message(
    *,
    to: str,
    sender: str,
    first_name: str | None,
    topic: Topic,
    language: Literal["it", "en"],
) -> EmailMessage:
    """Build the email that invites a caller to finish their request by email.

    Args:
        to: The caller's email.
        sender: The hotel's sending address.
        first_name: The caller's first name, if known.
        topic: What the caller was trying to do.
        language: The language of the call.

    Returns:
        A plain-text email. It promises that reception handles the reply, never a
        callback.
    """
    text = _FOLLOWUP[language]
    greeting = (
        text["greeting"].format(first_name=_one_line(first_name))
        if first_name
        else text["greeting_no_name"]
    )
    msg = EmailMessage()
    msg["From"] = f"{HOTEL_NAME} <{sender}>"
    msg["To"] = to
    msg["Subject"] = text["subject"].format(hotel=HOTEL_NAME)
    msg.set_content(
        text["body"].format(
            greeting=greeting, hotel=HOTEL_NAME, topic=_TOPICS[language][topic]
        )
    )
    return msg
