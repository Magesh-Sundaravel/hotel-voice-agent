# Tool contracts

One section per tool. Update in the same change as the code.

## TEMPLATE_tool_name
- Purpose: one line
- Input: field: type, ...
- Output: {ok: true, ...} | {ok: false, reason: str}
- Side effects: none | writes X
- Idempotent: yes (key: ...) | n/a
- Typical latency: ...

## check_availability
- Purpose: list the room types that have a free room for the whole stay and fit the party size.
- Input: check_in: date, check_out: date (exclusive), guests: int
- Output: {ok: true, options: [{room_type: str, rooms_free: int}]} | {ok: false, reason: str}
- Reasons: invalid_dates (check_out not after check_in, check_in in the past, or a stay longer than 30 nights), invalid_guests (guests below 1), too_many_guests (above every room type's max_guests)
- Side effects: none
- Idempotent: n/a (read-only)
- Typical latency: under 300 ms (in-memory now, one Supabase query later)
- Empty `options` is a valid answer (fully booked), not an error.

## get_rates
- Purpose: price a stay for one room type.
- Input: room_type: str, check_in: date, check_out: date (exclusive)
- Output: {ok: true, room_type: str, nights: int, total_eur: int, per_night_eur: [int]} | {ok: false, reason: str, valid_room_types: [str]}
- Reasons: unknown_room_type (`valid_room_types` lists the real names so the agent can offer them), invalid_dates (same rules as check_availability, including the 30 night cap), no_rate_for_dates
- `room_type` is matched case-insensitively and returned with the hotel's own spelling.
- Side effects: none
- Idempotent: n/a (read-only)
- Typical latency: under 300 ms
- A stay that crosses the low/high season boundary is priced night by night, hence `per_night_eur`.
