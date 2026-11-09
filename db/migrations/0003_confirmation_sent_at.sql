-- When the booking confirmation email was claimed for sending. Null means not sent
-- yet, or the details changed since (modify_booking clears it) and a new email is due.
alter table reservations add column confirmation_sent_at timestamptz;
