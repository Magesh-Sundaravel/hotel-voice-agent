# Tool contracts

One section per tool. Update in the same change as the code.

## What the model reads is part of the contract
The model decides when and how to call a tool from its description and its parameter descriptions, so both are contract, not decoration. Write them to Anthropic's guidance ("Define tools", best practices): at least four sentences saying what the tool does, when to use it, what it returns, what it does not do, and what each error `reason` means in plain words. Give every parameter a description.
- Tool descriptions live in `src/agent/registry.py`. Parameter descriptions live in each tool's input model (`Field(description=...)`); the date ones are shared in `src/tools/__init__.py`.
- `tests/test_tool_specs.py` enforces: every parameter described, at least four sentences per tool, every `reason` named in the description, the real stay limit quoted from `MAX_STAY_NIGHTS`, and each tool pointing at the other for what it does not do.
- Changing a description changes `tools_hash` in the Langfuse run metadata, so run the evals before and after and compare the two experiments.

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
