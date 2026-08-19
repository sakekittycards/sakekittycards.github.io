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
 *   revealAt : optional 'YYYY-MM-DD' — keep the event masked (show `name`/`loc`
 *              as a teaser) until this date, then auto-swap to realName/realLoc.
 *   realName / realLoc : the true name + venue, shown only on/after revealAt.
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
  { start: '2026-05-23', end: '2026-05-24', name: 'Collect-A-Con — Orlando',    loc: 'Orange County Convention Center · 9800 International Dr, Orlando, FL 32819', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-05-30', end: '2026-05-31', name: 'Syndicate Trade Show — Tampa', loc: 'Renaissance Tampa International Plaza Hotel · 4200 Jim Walter Blvd, Tampa, FL 33607', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-05-31',                     name: 'PGA Card Show',              loc: 'Palm Beach Gardens, FL' },
  { start: '2026-06-05', end: '2026-06-07', name: 'Culture Collision',          loc: '2000 Convention Center Concourse, College Park, GA 30337' },
  { start: '2026-06-13',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-06-14',                     name: 'Naples Card Show',           loc: 'The White Rose · 2320 Moulder Drive, Naples, FL 34120', hours: '10am–4pm' },
  { start: '2026-06-20', end: '2026-06-21', name: 'Collect-A-Con — Las Vegas',  loc: 'Las Vegas Convention Center · 3150 Paradise Rd, Las Vegas, NV 89109', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-06-21',                     name: 'Florida Regional Card Expo', loc: 'Caloosa Sound Convention Center · 1375 Monroe St, Fort Myers, FL 33901', hours: '10am–6pm' },
  { start: '2026-06-28',                     name: 'Cardichu — Pompano Beach',   loc: 'D1 · 1401 Green Road, Pompano Beach, FL 33064', hours: '9am–5pm' },
  { start: '2026-06-28',                     name: 'Pokekon',                    loc: 'DoubleTree by Hilton Fort Myers at Bell Tower Shops · Fort Myers, FL' },
  { start: '2026-07-04', end: '2026-07-05', name: 'Ocala TCG Trade N Play',     loc: 'Ocala, FL' },
  { start: '2026-07-11',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-07-12',                     name: 'PGA Card Show',              loc: 'Palm Beach Gardens, FL' },
  { start: '2026-07-18', end: '2026-07-19', name: 'TCG Trade N Play SuperCon',  loc: 'Florida State Fairgrounds — Entertainment Hall · Tampa, FL', hours: '10am–6pm' },
  { start: '2026-07-19',                     name: '👀 Secret Show — Stay Tuned', loc: 'Location revealed soon', hours: '10am–4pm', revealAt: '2026-06-25', realName: 'Naples Card Show', realLoc: 'The White Rose · 2320 Moulder Drive, Naples, FL 34120' },
  { start: '2026-07-26',                     name: 'Card Party S. Florida 4',    loc: 'Broward County Convention Center · 1950 Eisenhower Blvd, Fort Lauderdale, FL 33316' },
  { start: '2026-08-01', end: '2026-08-02', name: 'Collect-A-Con — Los Angeles', loc: 'Los Angeles Convention Center · 1201 S Figueroa St, Los Angeles, CA 90015', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-08-01',                     name: 'Delray Card Show',           loc: 'Delray Beach, FL' },
  { start: '2026-08-02',                     name: 'PGA Card Show',              loc: 'Palm Beach Gardens, FL' },
  { start: '2026-08-08',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-08-09',                     name: 'Cardichu — Pompano Beach',   loc: 'D1 · 1401 Green Road, Pompano Beach, FL 33064', hours: '9am–5pm' },
  { start: '2026-08-15', end: '2026-08-16', name: 'The Hobby Card Show 2026',   loc: 'Broward County Convention Center — Grand Ballroom, 3rd Floor · 1950 Eisenhower Blvd, Fort Lauderdale, FL 33316', hours: 'Sat & Sun 11am–5pm (VIP early access 10am)' },
  { start: '2026-08-22', end: '2026-08-23', name: 'Collect-A-Con — Charlotte',   loc: 'Charlotte Convention Center · Charlotte, NC', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-08-23',                     name: '👀 Secret Show — Stay Tuned', loc: 'Location revealed soon', hours: '10am–4pm', revealAt: '2026-06-25', realName: 'Naples Card Show', realLoc: 'The White Rose · 2320 Moulder Drive, Naples, FL 34120' },
  { start: '2026-08-29',                     name: 'Delray Card Show',           loc: 'Delray Beach, FL' },
  { start: '2026-09-05', end: '2026-09-06', name: 'TCG Takeover — Orlando',     loc: 'Dezerland Orlando · 5250 International Drive, Orlando, FL 32819' },
  { start: '2026-09-11', end: '2026-09-13', name: 'SWFL Super Card Show X2',    loc: 'Lee Civic Center · 11831 Bayshore Road, North Ft. Myers, FL 33917', hours: 'Fri 5pm setup · Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-09-12', end: '2026-09-13', name: 'Collect-A-Con — San Francisco', loc: 'San Mateo County Convention Center · San Mateo, CA', hours: 'Sat 10am–6pm · Sun 10am–5pm' },
  { start: '2026-09-19', end: '2026-09-20', name: 'Lakeland TCG Trade-N-Play',  loc: 'RP Funding Center · 701 W Lime St, Lakeland, FL 33815' },
  { start: '2026-09-19',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-09-20',                     name: 'PGA Card Show',              loc: 'Palm Beach Gardens, FL' },
  { start: '2026-09-26',                     name: 'Delray Card Show',           loc: 'Delray Beach, FL' },
  { start: '2026-10-04',                     name: 'Florida Regional Card Expo', loc: 'Caloosa Sound Convention Center · 1375 Monroe St, Fort Myers, FL 33901', hours: '10am–6pm' },
  { start: '2026-10-10',                     name: 'Clearwater TCG Trade-N-Play', loc: 'Matheos Hall · 409 Old Coachman Road, Clearwater, FL 33765', hours: '10am–6pm' },
  { start: '2026-10-10',                     name: 'Stuart Card Show',           loc: 'The Flagler · 201 SW Flagler Ave, Stuart, FL 34994', hours: '10am–5pm' },
  { start: '2026-10-24',                     name: 'Delray Card Show',           loc: 'Delray Beach, FL' },
  { start: '2026-10-31', end: '2026-11-01', name: 'Fairgrounds Card Expo Convention', loc: 'South Florida Fairgrounds · Southern Blvd, West Palm Beach, FL' },
  { start: '2026-11-13', end: '2026-11-15', name: 'Palm Beach Card Show',       loc: 'Palm Beach County Convention Center · 650 Okeechobee Blvd, West Palm Beach, FL 33401' },
  { start: '2026-11-21', end: '2026-11-22', name: 'Florida Regional Card Expo', loc: 'Caloosa Sound Convention Center · 1375 Monroe St, Fort Myers, FL 33901', hours: 'Sat & Sun 10am–6pm' },
  { start: '2026-12-12',                     name: 'PokeKon Fest — Miami',       loc: 'Miami Airport Convention Center (DoubleTree by Hilton) — MACC-1 Ballroom · 711 NW 72nd Ave, Miami, FL 33126', hours: '10am–5pm · Cosplay contest 4pm' },
  { start: '2026-12-26',                     name: 'Delray Card Show',           loc: 'Delray Beach, FL' },
  { start: '2026-12-27',                     name: 'PokeKon Fest — Fort Myers',  loc: 'DoubleTree by Hilton Fort Myers at Bell Tower Shops · 13051 Bell Tower Drive, Fort Myers, FL 33907', hours: '10am–5pm · Free parking · Kids under 11 free' },
  { start: '2027-01-09', end: '2027-01-10', name: 'The Hobby Card Show',        loc: 'Broward County Convention Center · 1950 Eisenhower Blvd, Fort Lauderdale, FL 33316' },
];
