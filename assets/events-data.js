/**
 * Shared event-schedule data — loaded by both `events.html` (public calendar)
 * and `vendor-portal.html` (post-auth vendor view).
 *
 * Edit this file ONLY — both pages render from `window.SK_EVENTS`, so a change
 * here updates both places at once. (Used to be inlined in events.html; moved
 * out 2026-05-13 when the vendor portal was added.)
 *
 * Schema:
 *   start  : 'YYYY-MM-DD' (required)
 *   end    : 'YYYY-MM-DD' (optional, for multi-day shows)
 *   name   : display title
 *   loc    : venue + address
 *   hours  : optional, free-form
 *   type   : optional, 'whatnot' for online-only streams
 */
window.SK_EVENTS = [
  { start: '2026-04-25', end: '2026-04-26', name: 'Bradenton TCG',              loc: 'Manatee County Fairgrounds — Veterans Expo Hall · 1402 14th Ave W, Palmetto, FL 34221', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-05-01',                     name: 'Whatnot Stream',             loc: 'Online', hours: '12pm–6pm', type: 'whatnot' },
  { start: '2026-05-02', end: '2026-05-03', name: 'Coral Springs Card Show — The BIG SHOW!', loc: 'Tribe Volleyball · 1801 Green Road, Deerfield Beach, FL 33064', hours: 'Sat & Sun 10am–4pm' },
  { start: '2026-05-06',                     name: 'Whatnot Stream',             loc: 'Online', hours: '12pm–6pm', type: 'whatnot' },
  { start: '2026-05-09', end: '2026-05-10', name: 'Collect-A-Con — Cleveland',   loc: 'Huntington Convention Center · 300 Lakeside Ave E, Cleveland, OH 44113', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-05-10',                     name: 'Naples Card Show',           loc: 'The White Rose · 2320 Moulder Drive, Naples, FL 34120', hours: '10am–4pm (VIP early access 9am)' },
  { start: '2026-05-16',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-05-17',                     name: 'Cardichu — Pompano Beach',   loc: 'D1 · 1401 Green Road, Pompano Beach, FL 33064', hours: '9am–5pm' },
  { start: '2026-05-23', end: '2026-05-24', name: 'Collect-A-Con',              loc: 'Orange County Convention Center · 9800 International Dr, Orlando, FL 32819', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-05-30', end: '2026-05-31', name: 'Syndicate Trade Show — Tampa', loc: 'Renaissance Tampa International Plaza Hotel · 4200 Jim Walter Blvd, Tampa, FL 33607', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-05-31',                     name: 'PGA Card Show',              loc: 'Palm Beach Gardens, FL' },
  { start: '2026-06-05', end: '2026-06-07', name: 'Culture Collision',          loc: '2000 Convention Center Concourse, College Park, GA 30337' },
  { start: '2026-06-13',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-06-14',                     name: 'Naples Card Show',           loc: 'The White Rose · 2320 Moulder Drive, Naples, FL 34120', hours: '10am–4pm' },
  { start: '2026-06-20', end: '2026-06-21', name: 'Collect-A-Con',              loc: 'Las Vegas Convention Center · 3150 Paradise Rd, Las Vegas, NV 89109', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-06-21',                     name: 'Florida Regional Card Expo', loc: 'Caloosa Sound Convention Center · 1375 Monroe St, Fort Myers, FL 33901', hours: '10am–6pm' },
  { start: '2026-06-28',                     name: 'Cardichu — Pompano Beach',   loc: 'D1 · 1401 Green Road, Pompano Beach, FL 33064', hours: '9am–5pm' },
  { start: '2026-06-28',                     name: 'Pokekon',                    loc: 'DoubleTree by Hilton Fort Myers at Bell Tower Shops · Fort Myers, FL' },
  { start: '2026-07-04', end: '2026-07-05', name: 'Ocala TCG Trade N Play',     loc: 'Ocala, FL' },
  { start: '2026-07-11',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-07-12',                     name: 'PGA Card Show',              loc: 'Palm Beach Gardens, FL' },
  { start: '2026-07-18', end: '2026-07-19', name: 'TCG Trade N Play SuperCon',  loc: 'Florida State Fairgrounds — Entertainment Hall · Tampa, FL' },
  { start: '2026-07-26',                     name: 'Card Party S. Florida 4',    loc: 'Broward County Convention Center · 1950 Eisenhower Blvd, Fort Lauderdale, FL 33316' },
  { start: '2026-08-08',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-08-09',                     name: 'Cardichu — Pompano Beach',   loc: 'D1 · 1401 Green Road, Pompano Beach, FL 33064', hours: '9am–5pm' },
  { start: '2026-08-15', end: '2026-08-16', name: 'The Hobby Card Show',        loc: 'Broward County Convention Center — Grand Ballroom, 3rd Floor · 1950 Eisenhower Blvd, Fort Lauderdale, FL 33316', hours: 'Sat & Sun 11am–5pm (VIP early access 10am)' },
  { start: '2026-09-11', end: '2026-09-13', name: 'Southwest Florida Big Show', loc: 'Fort Myers, FL' },
  { start: '2026-09-19',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-10-10',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-11-13', end: '2026-11-15', name: 'Palm Beach Card Show',       loc: 'Palm Beach County Convention Center · 650 Okeechobee Blvd, West Palm Beach, FL 33401' },
];
