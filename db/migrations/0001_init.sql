-- Initial schema. Mirrors docs/data-model.md; change both together.
-- RLS is on with no policies: only the backend's database role can read or write,
-- so the public anon key can never reach guest data through Supabase's REST API.

create extension if not exists btree_gist;

create table guests (
    id uuid primary key default gen_random_uuid(),
    first_name text not null,
    last_name text not null,
    phone text not null unique,
    email text,
    language text not null check (language in ('it', 'en')),
    created_at timestamptz not null default now()
);

create table room_types (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    description text not null default '',
    max_guests int not null check (max_guests > 0),
    base_beds text not null default ''
);

create table rooms (
    id uuid primary key default gen_random_uuid(),
    number text not null unique,
    floor int not null,
    room_type_id uuid not null references room_types (id),
    is_active bool not null default true
);

create table rates (
    id uuid primary key default gen_random_uuid(),
    room_type_id uuid not null references room_types (id),
    valid_from date not null,
    valid_to date not null,
    price_per_night_cents int not null check (price_per_night_cents >= 0),
    currency text not null default 'EUR',
    check (valid_from <= valid_to)
);

create table reservations (
    id uuid primary key default gen_random_uuid(),
    reference text not null unique,
    guest_id uuid not null references guests (id),
    room_id uuid not null references rooms (id),
    check_in date not null,
    check_out date not null,
    adults int not null check (adults > 0),
    status text not null check (status in ('confirmed', 'cancelled')),
    total_cents int not null check (total_cents >= 0),
    idempotency_key text not null unique,
    created_at timestamptz not null default now(),
    cancelled_at timestamptz,
    check (check_in < check_out),
    -- check_out is exclusive, so back-to-back stays on one room do not overlap.
    exclude using gist (
        room_id with =,
        daterange(check_in, check_out) with &&
    ) where (status = 'confirmed')
);

create table call_log (
    id uuid primary key default gen_random_uuid(),
    call_id text not null unique,
    guest_id uuid references guests (id),
    language text not null check (language in ('it', 'en')),
    started_at timestamptz not null default now(),
    ended_at timestamptz,
    outcome text,
    needs_followup bool not null default false,
    followup_reason text,
    reservation_id uuid references reservations (id)
);

alter table guests enable row level security;
alter table room_types enable row level security;
alter table rooms enable row level security;
alter table rates enable row level security;
alter table reservations enable row level security;
alter table call_log enable row level security;
