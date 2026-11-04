# Sona Play native Android app

Every push to `main` builds the app on GitHub (Actions tab) and publishes `SonaPlay-native.apk` under Releases.

One time setup
1. Render > Environment: set ALLOWED_ORIGINS to `https://sonaplaiy.netlify.app,https://localhost`
2. Supabase > Authentication > URL Configuration > Redirect URLs: add `com.skyline.sonaplay://auth`
3. Phone: open github.com/helalink-site/sonaplay/releases, download the newest SonaPlay-native.apk and install it (allow "install unknown apps" for your browser).
