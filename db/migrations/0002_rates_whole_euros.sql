-- Rates are quoted to callers in whole euros, so stray cents would be silently
-- dropped. Refuse them at the source.
alter table rates
    add constraint rates_whole_euros check (price_per_night_cents % 100 = 0);
