"""Agent tools, one module each."""

MAX_STAY_NIGHTS = 30

# Parameter descriptions both tools show the model, so they stay identical.
CHECK_IN_DESCRIPTION = (
    "Arrival date, the first night of the stay, as YYYY-MM-DD. Must be today or "
    "later. Work out words like 'tomorrow' or 'next Friday' from today's date."
)
CHECK_OUT_DESCRIPTION = (
    "Departure date as YYYY-MM-DD. This is the day the guest leaves, not a night "
    "they stay, so it must be after check_in: check_in 2026-12-10 with check_out "
    "2026-12-12 is two nights."
)
