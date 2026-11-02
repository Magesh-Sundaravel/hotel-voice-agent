# Tool contracts

One section per tool. Update in the same change as the code.

## TEMPLATE_tool_name
- Purpose: one line
- Input: field: type, ...
- Output: {ok: true, ...} | {ok: false, reason: str}
- Side effects: none | writes X
- Idempotent: yes (key: ...) | n/a
- Typical latency: ...
