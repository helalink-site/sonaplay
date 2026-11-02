# Sona Play (Version 3, Skyline Technologies) , release v6

```
index.html config.js manifest.json sw.js _headers netlify.toml   frontend (Netlify)
backend/   app.py security.py Dockerfile requirements.txt        API (Render)
mobile/    Expo React Native app (see mobile/README.md)
supabase/  upgrade/  001_schema.sql, 002_region_admin_analytics.sql   run on your EXISTING project
           fresh/    full_setup.sql (001+002 in one file), reset_public_schema.sql
           config.toml                                             auth settings for the Supabase CLI
```

## Supabase: pick one
- **Existing project:** SQL Editor, run in this order: `upgrade/001_schema.sql`, `002_region_admin_analytics.sql`, `003_admin_extras.sql`, `004_legal_invites_users.sql`. Each only adds what is missing and is safe to run again. If you only have 001-003 already, run just **004**.
- **New or wiped project:** run `fresh/full_setup.sql` once (it now includes 001 to 004). To wipe an old project first, run `fresh/reset_public_schema.sql` (it deletes all public tables and data; users in Authentication stay).
- Always run 001 before 002. Re-running 001 later removes the grants 002 adds, so run 002 again after it.

## Auth settings (Dashboard > Authentication)
1. Providers: Email on with **Confirm email** on. Google on (add your Client ID and Secret).
2. URL Configuration: Site URL = your Netlify URL. Redirect URLs: add `https://YOUR-SITE.netlify.app/**`.
3. Password minimum length 8 (the app now checks 8).
4. Optional: turn on CAPTCHA protection (Authentication > Attack Protection).

## Admin (later)
Make yourself admin once (SQL Editor): `insert into admins (user_id) select id from auth.users where email = 'you@email.com';`
The admin panel will call these functions: `admin_overview`, `admin_signups('day'|'week'|'month', n)`, `admin_active(...)`, `admin_by_region`, `admin_list_users`, `admin_send_broadcast(title, body, region)`. They check `is_admin()` inside, so normal users get "not allowed".

## Region
Sign-up now requires a region. Google sign-ins and older accounts are asked once on first open. It is stored in the profile and used for the admin region charts.

## Backend (Render) and frontend (Netlify)
Backend variables are in `.env.example`; `ALLOWED_ORIGINS` must be your Netlify URL; leave `FLASK_DEBUG` unset. Edit `config.js` (API and Supabase URL and anon key) and the `connect-src` hosts in `_headers`. The service_role key lives on Render only.

## Notifications setup (new release alerts, bell, push)
1. Run the Supabase SQL (002 turns on realtime for the bell).
2. Render variables: `SUPABASE_SERVICE_ROLE_KEY`, `CRON_SECRET`, `VAPID_PRIVATE_KEY`, `VAPID_EMAIL`. Generate keys with `npx web-push generate-vapid-keys`, and put the PUBLIC key in `config.js` as `VAPID_PUBLIC`.
3. Free Render instances sleep, so use an external scheduler (for example cron-job.org) every 30 minutes: `POST https://YOUR-API/api/jobs/check-releases` with header `X-Cron-Secret: <CRON_SECRET>`.
Follows and genres are saved to Supabase automatically, so the job knows who follows whom. The first time an artist is checked it only records their latest song, so nobody gets a flood of old releases.

## Known limits
Un-following on one device can be undone by another device that still has the old list. The mobile app (`mobile/`) has not been run on a device and has no downloads, playlists or equalizer yet. The admin panel is kept separate for later.


## What v6 adds
- Google logo on the sign-in screen. The play and pause buttons (player and mini player) show a spinner while a song loads
- Alerts are live: the bell, the Alerts page and a banner update the moment an alert (new song or admin message) is created. Phone push also works when the app is closed
- Share uses your own link `https://YOUR-SITE/?play=VIDEOID&t=Title` with the text "Title by Artist, on Sona Play". No `index.html` in it
- Install prompt on the website without screenshots (manifest `screenshots` removed). It returns after 3 days if dismissed. iPhone shows the Add to Home Screen steps
- Settings > Invite friends: a link with the user's username `https://YOUR-SITE/?ref=username`. New users who open it are linked to the inviter (admin shows Top inviters)
- Music keeps playing when the app is minimised (lock-screen and notification controls). The exit box says Minimise or Exit; only Exit stops the music
- Downloads show real progress (cover fills, then a check)
- Admin panel: add users, delete users, edit Privacy Policy and Terms (type or upload a .txt), send alerts, top inviters. See below

## Admin panel (`/admin`)
Log in with an admin account (see "Admin (later)" above to make yourself admin). Tabs: Overview, Regions, Users (add / delete), Broadcast, Settings, Legal.
- Add and delete users call the backend, so Render needs `SUPABASE_SERVICE_ROLE_KEY`. The backend checks that you are an admin before it does anything
- Broadcast: apps that are open show it instantly; the backend sends the phone push straight away
- Legal: saved text shows in the app, and on `/privacy` and `/terms`

## Push on phones (needs once)
`npx web-push generate-vapid-keys`; PUBLIC key into `config.js` (`VAPID_PUBLIC`), PRIVATE key and `VAPID_EMAIL` on Render. Add `pywebpush` to `backend/requirements.txt` if it is not there.

## Not tested here
The app was run in a test browser with simulated Supabase and API answers. It was not run against your real Supabase, YouTube or a real phone, and the new SQL file was not run on a real database.

## v6.1 fixes
- Covers no longer draw over the mini player and bottom bar (stacking order fixed)
- Real connection check: when data is on but there is no usable connection, the app shows "No internet connection" (Try again / My downloads) or "Could not load songs" instead of empty headings, hides empty sections and Explore links, and recovers by itself when the connection returns
- No more welcome screen when the app opens without a connection; the saved login is restored as soon as the connection is back
- Music resumes if the system pauses it, reconnects a broken stream (3 tries), and a pause you press yourself is respected
- Admin > Broadcast > "Send a test to my phone" shows whether saving, live delivery and push are ready
