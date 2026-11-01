# Sona Play (Version 3, Skyline Technologies)

```
index.html config.js manifest.json sw.js _headers netlify.toml   frontend (Netlify)
backend/   app.py security.py Dockerfile requirements.txt        API (Render)
mobile/    Expo React Native app (see mobile/README.md)
supabase/  upgrade/  001_schema.sql, 002_region_admin_analytics.sql   run on your EXISTING project
           fresh/    full_setup.sql (001+002 in one file), reset_public_schema.sql
           config.toml                                             auth settings for the Supabase CLI
```

## Supabase: pick one
- **Existing project:** SQL Editor, run `upgrade/001_schema.sql`, then `upgrade/002_region_admin_analytics.sql`. Both only add what is missing.
- **New or wiped project:** run `fresh/full_setup.sql` once. To wipe an old project first, run `fresh/reset_public_schema.sql` (it deletes all public tables and data; users in Authentication stay).
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
