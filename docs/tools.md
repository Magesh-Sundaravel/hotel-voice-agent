# Tool contracts

One section per tool. Update in the same change as the code.

## What the model reads is part of the contract
The model decides when and how to call a tool from its description and its parameter descriptions, so both are contract, not decoration. Write them to Anthropic's guidance ("Define tools", best practices): at least four sentences saying what the tool does, when to use it, what it returns, what it does not do, and what each error `reason` means in plain words. Give every parameter a description.
- Tool descriptions live in `src/agent/registry.py`. Parameter descriptions live in each tool's input model (`Field(description=...)`); the date ones are shared in `src/tools/__init__.py`.
- `tests/test_tool_specs.py` enforces: every parameter described, at least four sentences per tool, every `reason` named in the description, the real stay limit quoted from `MAX_STAY_NIGHTS`, and each tool pointing at the other for what it does not do.
- Changing a description changes `tools_hash` in the Langfuse run metadata, so run the evals before and after and compare the two experiments.

## Failures any tool can return
The loop (`src/agent/loop.py`, also behind the webhooks) returns these before or around the tool itself:
- unknown_tool: no tool with that name
- invalid_arguments: the arguments do not fit the schema; `fields: [str]` names the bad arguments (names only, never values; empty when the JSON itself is broken)
- tool_timeout: the tool took longer than 1.5 s
- tool_error: the tool raised an unexpected error

## TEMPLATE_tool_name
- Purpose: one line
- Input: field: type, ...
- Output: {ok: true, ...} | {ok: false, reason: str}
- Side effects: none | writes X
- Idempotent: yes (key: ...) | n/a
- Typical latency: ...

## check_availability
- Purpose: list the room types that have a free room for the whole stay and fit the party size.
- Use when: the arrival date, the departure date and the party size are known. Do not wait for the caller to choose a room type; the result is what gets offered.
- Does not: return prices (that is get_rates) or make a booking.
- Input: check_in: date (arrival, the first night, today or later), check_out: date (departure day, exclusive), guests: int (everyone staying, children included, at least 1)
- Output: {ok: true, options: [{room_type: str, rooms_free: int}]} | {ok: false, reason: str}
- Reasons: invalid_dates (check_out not after check_in, check_in in the past, or a stay longer than 30 nights), invalid_guests (guests below 1), too_many_guests (above every room type's max_guests)
- Side effects: none
- Idempotent: n/a (read-only)
- Typical latency: under 300 ms (in-memory now, one Supabase query later)
- Empty `options` is a valid answer (fully booked), not an error.

## get_rates
- Purpose: price a stay for one room type.
- Use when: the caller has chosen a room type from a check_availability result (which needs the guest count) and the arrival and departure dates are known.
- Does not: check that the room is free or that it fits the party (call check_availability first), or make a booking.
- Input: room_type: str (name from a check_availability result, any case), check_in: date (arrival, the first night, today or later), check_out: date (departure day, exclusive)
- Output: {ok: true, room_type: str, nights: int, total_eur: int, per_night_eur: [int]} | {ok: false, reason: str, valid_room_types: [str]}
- Reasons: unknown_room_type (`valid_room_types` lists the real names so the agent can offer them), invalid_dates (same rules as check_availability, including the 30 night cap), no_rate_for_dates (some night of the stay has no price set)
- `room_type` is matched case-insensitively and returned with the hotel's own spelling.
- Side effects: none
- Idempotent: n/a (read-only)
- Typical latency: under 300 ms
- A stay that crosses the low/high season boundary is priced night by night, hence `per_night_eur`.

## Call context (not a tool)
The booking tools need two facts the model must never generate: the call's `call_id` and the caller's phone (E.164, or none when the number is withheld). They come from a `CallContext` bound when the registry is built and never appear in a tool's parameters. The text CLI makes a random `call_id` and takes `--caller-phone`. Each eval case sets its own caller phone, or none. In step 1 the ElevenLabs webhook fills the same object (`system__conversation_id`, `system__caller_id`).

Rules shared by the booking tools:
- The agent reads the full booking back and gets an explicit yes before `create_booking`, `modify_booking` or `cancel_booking`.
- `reference` is 6 digits, said digit by digit.
- `get_booking`, `modify_booking` and `cancel_booking` need the reference **and** the guest's last name (any case). A wrong reference and a wrong name give the same `not_found`, so a caller cannot probe which references exist.
- Prices are always computed by the server from `rates`; the model never sends a price.
- Policy: free cancellation until 48 hours before check-in, which is 15:00 Europe/Rome on the arrival day.

## get_guest_info
- Purpose: find out whether the caller is a returning guest, from their caller ID.
- Use when: the caller wants to book and you need their name. Confirm it ("am I speaking with Giulia Rossi?") before using anything stored. If they say no, they are someone else on that phone: ask for their own mobile number and pass it to create_booking.
- Does not: search by name, read a booking, or create a guest (guests are created by create_booking).
- Input: none (the caller ID comes from the call context)
- Output: {ok: true, found: true, first_name: str, last_name: str, has_email: bool} | {ok: true, found: false}
- `found: false` covers both "no match" and "number withheld"; either way, ask for the name.
- The stored email and phone are never returned, only whether an email is on file.
- Side effects: none
- Idempotent: n/a (read-only)
- Typical latency: under 300 ms

## create_booking
- Purpose: book one room for a stay.
- Use when: check_availability has shown the room type is free, get_rates has priced it, you have the guest's first and last name, and the caller has said yes to the full read-back (dates, room type, adults, total price).
- Does not: book more than one room, take payment, or send the confirmation email (use send_confirmation_email).
- Input: room_type: str (any case), check_in: date, check_out: date (exclusive), adults: int (at least 1), first_name: str, last_name: str, language: "it" | "en" (the language the caller is speaking), email: str | null (optional; spelled back once before booking), phone: str | null (E.164; only when the caller ID is withheld, or the caller is not the guest get_guest_info found)
- The guest's phone is `phone` if given, otherwise the caller ID. A guest with that phone and the same name (any case) is reused, and a new email replaces the stored one. Name and phone are never overwritten.
- The room is the lowest-numbered free room of the type for the whole stay.
- Output: {ok: true, reference: str, room_type: str, check_in: date, check_out: date, nights: int, adults: int, total_eur: int, email_on_file: bool} | {ok: false, reason: str}
- Reasons:
  - invalid_dates: same rules as check_availability, including the 30 night cap
  - invalid_guests: adults below 1
  - unknown_room_type: not one of the hotel's room types
  - too_many_guests: more adults than this room type holds
  - no_availability: no room of the type is free for the whole stay (it may have been taken during the call); offer the other free types
  - no_rate_for_dates: some night has no price set
  - phone_required: no `phone` was given and the caller ID is withheld; ask for a mobile number
  - invalid_phone: the `phone` given is not in international format (E.164, with the country code); ask again
  - phone_belongs_to_other_guest: the phone is on file under a different name; ask for the caller's own number
  - invalid_email: the email is not a valid address; spell it back again
- Side effects: writes a reservation, and a guest (insert, or email update)
- Idempotent: yes (key: call_id + room type + dates + phone). A retried call returns the same reservation.
- Typical latency: under 500 ms (one transaction)

## get_booking
- Purpose: read back an existing booking.
- Use when: the caller wants to check, change or cancel a booking. Always call it first and read the details back before modify_booking or cancel_booking.
- Does not: change anything, or find a booking without its reference.
- Input: reference: str (6 digits), last_name: str (any case)
- Output: {ok: true, reference: str, status: "confirmed" | "cancelled", first_name: str, room_type: str, check_in: date, check_out: date, nights: int, adults: int, total_eur: int} | {ok: false, reason: str}
- Reasons: not_found (no booking with that reference and last name)
- Side effects: none
- Idempotent: n/a (read-only)
- Typical latency: under 300 ms

## modify_booking
- Purpose: change the dates, the number of adults or the room type of a confirmed booking, keeping its reference.
- Use when: get_booking has found the booking, get_rates has priced the new stay, and the caller has said yes to the new details and new total.
- Does not: cancel (use cancel_booking), change the guest's name, or modify a cancelled or finished stay.
- Input: reference: str, last_name: str, check_in: date | null, check_out: date | null, adults: int | null, room_type: str | null (at least one of the last four)
- Availability is checked as if this booking did not exist. The guest keeps the same room when it is still free and of the requested type; otherwise they get the lowest-numbered free room. The total is repriced.
- Output: same as get_booking | {ok: false, reason: str}
- Reasons:
  - not_found
  - cancelled: the booking is cancelled; offer a new booking instead
  - past_booking: the stay has already ended
  - nothing_to_change: no field was given
  - invalid_dates, invalid_guests, unknown_room_type, too_many_guests, no_availability, no_rate_for_dates: same as create_booking
- Side effects: updates the reservation and clears `confirmation_sent_at`, so send_confirmation_email sends the updated details
- Idempotent: yes. Applying the same change again returns the same booking.
- Typical latency: under 500 ms (one transaction)

## cancel_booking
- Purpose: cancel a booking.
- Use when: get_booking has found the booking and the caller has said yes to cancelling it.
- Does not: refund or charge anything, or cancel a stay that has already ended.
- Input: reference: str, last_name: str
- Output: {ok: true, reference: str, late_cancellation: bool} | {ok: false, reason: str}
- `late_cancellation` is true when the booking was cancelled less than 48 hours before check-in. Tell the caller the cancellation policy charge may apply. Do not name an amount.
- Reasons: not_found, past_booking (the stay has already ended)
- Side effects: sets the reservation to cancelled, which frees the room
- Idempotent: yes (by reference). Cancelling an already cancelled booking returns ok with its original `late_cancellation`.
- Typical latency: under 300 ms

## send_confirmation_email
- Purpose: email the guest a confirmation of a booking, with a calendar invite attached.
- Use when: create_booking or modify_booking has just succeeded. Call it straight away, without asking the caller again; the email address was settled during booking. Then say the email will arrive in a few minutes.
- Does not: take an email address (it only sends to the one on file, which create_booking stores), send a cancellation, or report whether the email was delivered.
- Input: reference: str (6 digits), last_name: str (any case), language: "it" | "en" (the language the caller is speaking now, not the one stored on the guest)
- Output: {ok: true} | {ok: false, reason: str}
- Reasons: not_found (no booking with that reference and last name), cancelled (the booking is cancelled), no_email_on_file (the guest gave no email; say nothing more about email)
- The email is sent by a background job after the tool returns. The job marks the booking, reads it again (so a modify made in between is what gets mailed), builds the email and sends it. Any failure in the job is logged with `guest_id` only, is not reported to the caller, and clears the mark.
- Content: plain text in `language`, with the reference, room type, dates and total said the way a person would, adults, check-in and check-out times, and the cancellation policy. The guest's email address never reaches the model.
- Attachment `booking.ics`: `METHOD:REQUEST`, the hotel's Gmail address as ORGANIZER, the guest as ATTENDEE with `RSVP=FALSE`, an all-day event from check_in to check_out (exclusive). UID `booking-<reference>@<sender domain>` stays the same for the life of the booking and SEQUENCE grows with each send (the send time in Unix seconds, valid until 2038, the iCalendar INTEGER limit), so a modify updates the event in the guest's calendar.
- Side effects: the job sets `reservations.confirmation_sent_at`, then sends one email. If the job fails, it clears only its own mark (matched on the time it set), so a later call can retry and a newer send is never undone. The app waits up to 10 s for queued sends at shutdown.
- Idempotent: yes (by reference). Once sent, calling again returns ok and sends nothing, until modify_booking changes the booking, which clears the mark.
- Typical latency: under 300 ms (the send itself runs after the reply)

## take_message
- Purpose: pass a message from the caller to the hotel's reception team. This is the handoff to a person: the agent never transfers the call.
- Use when: the caller asks for a person, a manager or a department, or wants something no other tool does (a special request, a complaint, a question the agent cannot answer). Get the caller's name and the message first. Then say the message has been passed to reception. Do not say when or how reception will reply: the agent never promises a callback.
- Does not: book, change or cancel anything, or email the caller.
- Input: first_name: str, last_name: str, message: str (the agent's short summary of what the caller wants, in the caller's language, 1 to 1000 characters), language: "it" | "en", email: str | null (optional), phone: str | null (E164; only when the caller ID is withheld or the caller wants to be reached on another number)
- The contact is `phone` if given, otherwise the caller ID, plus `email` if given. At least one of the two is required.
- Output: {ok: true} | {ok: false, reason: str}
- Reasons: contact_required (no caller ID, no phone and no email; ask for a phone number or an email), invalid_phone (not in international format; ask again), invalid_email (not a valid address; spell it back again)
- The message is emailed to the hotel's own inbox (`GMAIL_SENDER`) by a background job after the tool answers. A failure in the job is logged with the call_id only.
- Side effects: one email to the hotel; the call log gets `needs_followup` and `followup_reason = "message"`.
- Idempotent: yes, within one running server (key: call_id + message). A retried call sends nothing more, unless the earlier send failed: a failed send releases its key so a retry can send.
- Typical latency: under 50 ms (the send runs after the reply)

## send_followup_email
- Purpose: when a tool keeps failing, email the caller so they can write down what they need and reception can finish it by email.
- Use when: a tool has failed (tool_error or tool_timeout, or any failure that is not the caller's to fix), the agent has tried once more and it failed again. Offer the email first and call this only if the caller agrees.
- Does not: retry the failed tool, book anything, or say what went wrong. It does not take a message for staff (use take_message).
- Input: topic: "booking" | "change" | "cancellation" | "information" (what the caller was trying to do), language: "it" | "en", email: str | null (optional; spelled back once; without it the email on file for the caller ID is used)
- Output: {ok: true} | {ok: false, reason: str}
- Reasons: email_required (no email was given and none is on file for the caller ID; ask the caller to spell one), invalid_email (not a valid address; spell it back again)
- Content: plain text in `language`: an apology that the request could not be finished on the phone, what it was about, and an invitation to reply with the details. It promises that reception will handle the reply, never a callback. The guest's stored email never reaches the model.
- The email is sent by a background job after the tool answers. A failure in the job is logged with the call_id only.
- Side effects: one email to the caller; the call log gets `needs_followup` and `followup_reason = "tool_failure:<topic>"`.
- Idempotent: yes, within one running server (key: call_id + address, any case). A second call to the same address sends nothing more; a corrected address gets its own email. A failed send releases its key so a retry can send.
- Typical latency: under 300 ms (one guest lookup; the send runs after the reply)
