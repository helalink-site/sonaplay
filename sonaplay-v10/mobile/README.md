# Sona Play mobile (Expo / React Native)
1. Edit `src/config.js` (API, Supabase URL, anon key).
2. `npm install` then `npx expo start` (scan with Expo Go, or `npm run android`).
3. Build an APK/AAB: `npx eas build -p android`.
Uses the same Supabase tables and Flask API as the web app. Never put the service_role key here.
