# Data model (Supabase, PMS-style)

Hosted Supabase free tier. All access goes through `src/db/`. Everything here is fake data (see `.claude/rules/data.md`).
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
| price_per_night_cents | int | |
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
| language | text | `it` or `en` |
| started_at | timestamptz | |
| ended_at | timestamptz | nullable |
| outcome | text | e.g. `booked`, `modified`, `cancelled`, `info`, `failed` |
| needs_followup | bool | a follow-up email was or should have been sent |
| followup_reason | text | nullable; no PII |
| reservation_id | uuid fk reservations | nullable |

No transcripts and no names, phones or emails in this table. Traces go to Langfuse with masking.

## Seed hotel
Fictional data modelled on Sina Bernini Bristol, Rome (Piazza Barberini 23, five stars). Only the public name, address and room type names are real. Everything else is invented, and phone numbers are fake.

| Room type | Rooms | max_guests |
|---|---|---|
| Superior | 10 | 2 |
| Deluxe | 8 | 2 |
| Executive Deluxe Piazza View | 5 | 3 |
| Junior Suite | 4 | 3 |
| Suite | 2 | 4 |
| Barberini Penthouse Suite | 1 | 4 |

30 rooms in total. Rates are invented per night in EUR for the low and high seasons, rising with room type.

Hotel policies (invented, kept in settings and the system prompt, not in the database):
- Check-in 15:00, check-out 12:00
- Breakfast included
- Free cancellation until 48 hours before check-in
- No pets

Seed also includes a handful of fake guests and reservations (including overlapping stays on the same room type) so availability and conflict cases can be tested and evaluated.
