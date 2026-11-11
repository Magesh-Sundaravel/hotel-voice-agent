-- The seed hotel is now fictional (Hotel Corte Aurelia). Rename the two room types
-- that carried a real hotel's names; ids, rooms, rates and bookings are unchanged.
update room_types set name = 'Executive Deluxe Courtyard View'
    where name = 'Executive Deluxe Piazza View';
update room_types set name = 'Aurelia Penthouse Suite'
    where name = 'Barberini Penthouse Suite';
