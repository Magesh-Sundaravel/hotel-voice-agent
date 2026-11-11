# Data model (Supabase, PMS-style)

Hosted Supabase free tier, reached directly over asyncpg (see docs/decisions/004-asyncpg-not-supabase-client.md). All access goes through `src/db/`.
Schema: `db/migrations/*.sql`, applied with `uv run python -m src.db.migrate` (add `--seed` to load the seed hotel from `src/db/seed.py`). Everything here is fake data (see `.claude/rules/data.md`).
Dates are in Europe/Rome. A stay runs from `check_in` to `check_out`, and the check-out day is exclusive (the room is free for a new guest that day).
Room availability lives only here. There is no calendar integration.

## Tables

### guests
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | the only guest identifier that may be logged |
| first_name | text | |
| last_name | text | |
| phone | text unique | E.164, matched against the Telnyx caller ID |
| email | text | nullable; used for confirmations and follow-ups |
| language | text | `it` or `en` |
| created_at | timestamptz | |

A guest row is created only when a booking is made.

### room_types
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| name | text unique | |
| description | text | spoken-friendly, no markdown |
| max_guests | int | |
| base_beds | text | e.g. "one king or two twin" |

### rooms
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| number | text unique | |
| floor | int | |
| room_type_id | uuid fk room_types | |
| is_active | bool | |

### rates
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| room_type_id | uuid fk room_types | |
| valid_from | date | inclusive |
| valid_to | date | inclusive |
| price_per_night_cents | int | whole euros only (multiple of 100), because prices are quoted in euros |
| currency | text | `EUR` |

Two seasons per room type: low (Nov to Mar) and high (Apr to Oct). No weekend uplift.

### reservations
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| reference | text unique | short, easy to say aloud |
| guest_id | uuid fk guests | |
| room_id | uuid fk rooms | assigned at booking: lowest free room number of the chosen type |
| check_in | date | |
| check_out | date | exclusive |
| adults | int | |
| status | text | `confirmed` or `cancelled` |
| total_cents | int | |
| idempotency_key | text unique | `call_id` + room type + dates + guest; a retried tool call returns the same reservation |
| created_at | timestamptz | |
| cancelled_at | timestamptz | nullable |
| confirmation_sent_at | timestamptz | nullable; set when the confirmation email is claimed for sending, cleared on a failed send and by modify_booking (a new email is then due) |

Double-booking is blocked by the database:
`EXCLUDE USING gist (room_id WITH =, daterange(check_in, check_out) WITH &&) WHERE (status = 'confirmed')`
(needs the `btree_gist` extension). A cancelled reservation frees the room.
Modify and cancel are idempotent by `reference`.

### call_log
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| call_id | text unique | ElevenLabs conversation id; same value tagged on the Langfuse trace |
| guest_id | uuid fk guests | nullable |
| language | text | nullable; `it` or `en`, from the first tool that is given a language |
| started_at | timestamptz | |
| ended_at | timestamptz | nullable |
| outcome | text | nullable; `booked`, `modified`, `cancelled`, `message` (take_message) or `followup` (send_followup_email); the latest wins |
| needs_followup | bool | a follow-up email was or should have been sent |
| followup_reason | text | nullable; no PII |
| reservation_id | uuid fk reservations | nullable |

Written by the tool webhook (`src/voice/call_log.py`, `src/db/calls.py`): the first tool call in a call creates the row, later ones fill it in. A field left unset keeps its value, the latest outcome wins, and `needs_followup` once set stays set. `guest_id` comes from the reservation the call touched. A call that never uses a tool has no row. `ended_at` is not written yet (it needs ElevenLabs' post-call webhook).

A failed or slow write (over 0.5 s) is logged as a warning with the call_id only, and the tool's answer is returned anyway.

No transcripts and no names, phones or emails in this table. Traces go to Langfuse with masking.

## Seed hotel
A fictional hotel: Hotel Corte Aurelia, Via della Lupa 12, Rome, five stars. The hotel, its address number, room types, rates, guests and bookings are all invented, and phone numbers are fake.

| Room type | Rooms | max_guests |
|---|---|---|
| Superior | 10 | 2 |
| Deluxe | 8 | 2 |
| Executive Deluxe Courtyard View | 5 | 3 |
| Junior Suite | 4 | 3 |
| Suite | 2 | 4 |
| Aurelia Penthouse Suite | 1 | 4 |

30 rooms in total. Rates are invented per night in EUR for the low and high seasons, rising with room type.

Hotel policies (invented, kept in settings and the system prompt, not in the database):
- Check-in 15:00, check-out 12:00
- Breakfast included
- Free cancellation until 48 hours before check-in
- No pets

Seed also includes three fake guests and three reservations with fixed references (482913, 615204, 730158), including both Suites over New Year, so availability, conflict, modify and cancel cases can be tested and evaluated. They are defined once in `src/db/seed.py`.
