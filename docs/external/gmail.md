# Gmail API + Google OAuth + iCalendar (checked 2026-11-09)

## 1. Token refresh
Src: https://developers.google.com/identity/protocols/oauth2/web-server (section "Refreshing an access token")
- `POST https://oauth2.googleapis.com/token`, `Content-Type: application/x-www-form-urlencoded`.
- Form: `client_id`, `client_secret`, `grant_type=refresh_token`, `refresh_token`.
- 200 body: `access_token`, `expires_in` (sample 3920 s; treat as ~1 h, refresh early), `scope`, `token_type` (`Bearer`).
- No `refresh_token` in the refresh response sample: keep the original. Not stated as a rule (UNVERIFIED).
- Initial consent must use `access_type=offline` or no refresh token is issued.
- Revoked/expired: docs say `invalid_grant` = "token may have expired or has been invalidated", fix = re-consent. Body shape `{"error":"invalid_grant","error_description":"..."}` (HTTP 400) is the OAuth norm; exact text UNVERIFIED.
Src: https://developers.google.com/identity/protocols/oauth2 ("Refresh token expiration"), https://support.google.com/cloud/answer/15549945
- Refresh tokens die when: user revokes; unused 6 months; user changes password AND token has Gmail scopes; >100 tokens per account per client (oldest silently dropped); time-based access expires; admin policy.
- Publishing status "Testing" (external): refresh tokens expire after 7 days unless scopes are only basic profile/email/openid. Gmail scopes are not, so Testing = re-consent weekly.
- "In production" (click "Publish app"): no 7-day expiry. Unverified apps with sensitive/restricted scopes show an "unverified app" screen and are capped at 100 new users lifetime. For a single hotel account: publish to production, click through the warning once, skip verification.

## 2. Sending
Src: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send , https://developers.google.com/workspace/gmail/api/guides/sending , https://gmail.googleapis.com/$discovery/rest?version=v1
- Use the JSON endpoint: `POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send`, `Authorization: Bearer <access_token>`, `Content-Type: application/json`, body `{"raw": "<base64url RFC 2822 message>"}`.
- Upload variant: `POST https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/send?uploadType=media|multipart|resumable`, media `message/*` (e.g. `message/rfc822`). Not needed for small .ics mails.
- Size: upload maxSize 36700160 bytes (35 MiB, discovery doc). Size cap for the JSON `raw` variant is not stated (UNVERIFIED); irrelevant at our size.
- `raw`: "RFC 2822 formatted and base64url encoded". Google's Python sample: `base64.urlsafe_b64encode(msg.as_bytes()).decode()` (keeps `=` padding and works). Padding rules not stated (UNVERIFIED).
- Response: a Message resource; expect `id`, `threadId`, `labelIds` (e.g. SENT). Store `id`/`threadId` if read-later needs threading.
- From header: docs/samples just set `From`. Whether Gmail rewrites a non-send-as From to the account address is not stated in API docs (UNVERIFIED). Set From to the hotel account address itself.

## 3. MIME with .ics
Src: https://www.rfc-editor.org/rfc/rfc6047.html (iMIP), guides/sending above
- `multipart/mixed`: part 1 `text/plain; charset=utf-8`; part 2 `text/calendar; method=PUBLISH; charset=UTF-8` with `Content-Disposition: attachment; filename="booking.ics"`.
- `method` param MUST match the iCalendar `METHOD` (case-insensitive). `charset=UTF-8` required if non-ASCII (Italian accents). Non-ASCII needs base64 or quoted-printable CTE.
- Clients must dispatch on Content-Type, not the filename extension.
- Whether Gmail/Outlook show an "add to calendar" card for PUBLISH (vs REQUEST) is not documented by Google or Microsoft (UNVERIFIED). Test with both on the first real send.
- Stdlib `email.message.EmailMessage` is what Google's own Python sample uses; fine. `msg.set_content(text)` + `msg.add_attachment(ics, maintype="text", subtype="calendar", filename=..., params={"method": "PUBLISH"})`.
- Pitfall (from CPython contentmanager behaviour, UNVERIFIED for our exact call): a `str` attachment is re-split on line endings and re-joined with the policy linesep, which turns CRLF into LF under the default policy. Pass the .ics as UTF-8 `bytes` (gets base64) or serialize with `email.policy.SMTP`. A unit test should assert CRLF after round-trip.

## 4. Scopes
Src: https://developers.google.com/workspace/gmail/api/auth/scopes
- Send-only: `https://www.googleapis.com/auth/gmail.send` = Sensitive.
- Send + read: add `https://www.googleapis.com/auth/gmail.readonly` = Restricted (so are `gmail.modify`, `gmail.metadata`, `gmail.compose`, `mail.google.com/`).
- Sensitive: OAuth app verification. Restricted: restricted-scope verification plus a security assessment if data is stored/sent through servers. Both are skippable only by staying unverified (warning + 100-user cap, see section 1).
- Discovery doc also lists `gmail.send.self` for send; not on the scopes page (UNVERIFIED meaning, presumably send to self only).
- Adding `gmail.readonly` later means a new consent and a new refresh token. Requesting both now avoids that.

## 5. Quotas and limits
Src: https://developers.google.com/workspace/gmail/api/reference/quota , https://support.google.com/mail/answer/22839
- 1,200,000 units/min per project; 6,000 units/min per user per project. `messages.send` = 100 units (so ~60 sends/min/user). `messages.list` = 5, `messages.get` = 20 (60 for format full/raw).
- Max 500 recipients per message. Quota page says exceeding limits "is planned to incur charges" on the Cloud billing account later in 2026. Demo volume is far below.
- Personal Gmail: >500 emails/day trips a send limit (1-24 h lockout). Whether API sends count toward it is not stated (UNVERIFIED, assume yes).
- Latency: not documented (UNVERIFIED). Token refresh + send are two round trips; cache the access token and send in a background task, not inside the 1.5 s tool budget.

## 6. iCalendar essentials (all-day stay)
Src: https://www.rfc-editor.org/rfc/rfc5545.html , https://www.rfc-editor.org/rfc/rfc5546.html (iTIP 3.2.1, 3.2.5)
- VCALENDAR MUST have `PRODID`, `VERSION:2.0`; add `METHOD:PUBLISH`.
- VEVENT MUST have `UID`, `DTSTAMP` (UTC, `...Z`). PUBLISH also requires `DTSTART`, `SUMMARY`, and `ORGANIZER` ("MUST be present"); `ATTENDEE` not allowed in PUBLISH.
- Stay: `DTSTART;VALUE=DATE:20261202`, `DTEND;VALUE=DATE:<checkout date>`. DTEND is non-inclusive and must also be DATE. (Use checkout day if the event means nights stayed through checkout morning; checkout+1 to show the checkout day too.)
- Lines end CRLF. Lines SHOULD NOT exceed 75 octets: fold by CRLF + one space (count octets, not chars, for UTF-8).
- TEXT escaping: `\\` for backslash, `\,` `\;` for comma/semicolon, newline as `\n`; colons NOT escaped.
- Updates: same `UID`, higher `SEQUENCE` supersedes; SEQUENCE MUST be incremented when DTSTART/DTEND/STATUS change; tie broken by later DTSTAMP. SEQUENCE must be present if > 0.
- Cancel: `METHOD:CANCEL`, same UID, incremented SEQUENCE, `STATUS:CANCELLED`. Not a PUBLISH.
- Whether Gmail/Google Calendar/Outlook apply PUBLISH updates or CANCEL to an event the guest already added from an attachment: UNVERIFIED. Many clients only track REQUEST invites with ATTENDEE; test.

## Contradictions with docs/architecture.md
- "Cancellation (same .ics UID, ... cancelled)": RFC 5546 cancels with METHOD:CANCEL + STATUS:CANCELLED, not PUBLISH. Client support for updates/cancels of PUBLISHed events is UNVERIFIED; plan may need METHOD:REQUEST with the guest as ATTENDEE, which changes the email into a real invite (RSVP buttons).
- PUBLISH requires ORGANIZER (hotel address); not mentioned in the plan.
- "Scope: send + read": read means `gmail.readonly`, a Restricted scope. Fine unverified for one account, but the app MUST be "In production", or the refresh token dies every 7 days. Changing the hotel account password also kills it.
- Architecture is silent on Testing vs Production status; that is the main runtime risk for "no human in the loop".
