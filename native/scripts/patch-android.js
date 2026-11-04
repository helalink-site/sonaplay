// Adds permissions and the sign-in return link to the generated Android project.
const fs = require('fs'), path = require('path');
const f = path.resolve(__dirname, '..', 'android', 'app', 'src', 'main', 'AndroidManifest.xml');
let x = fs.readFileSync(f, 'utf8');
const perms = ['WAKE_LOCK', 'FOREGROUND_SERVICE', 'FOREGROUND_SERVICE_MEDIA_PLAYBACK', 'POST_NOTIFICATIONS', 'ACCESS_NETWORK_STATE']
  .filter(p => !x.includes('android.permission.' + p))
  .map(p => '    <uses-permission android:name="android.permission.' + p + '" />').join('\n');
if (perms) x = x.replace('</manifest>', perms + '\n</manifest>');
if (!x.includes('com.skyline.sonaplay')) {
  const filter = '\n            <intent-filter>\n                <action android:name="android.intent.action.VIEW" />\n                <category android:name="android.intent.category.DEFAULT" />\n                <category android:name="android.intent.category.BROWSABLE" />\n                <data android:scheme="com.skyline.sonaplay" android:host="auth" />\n            </intent-filter>\n        ';
  x = x.replace('</activity>', filter + '</activity>');
}
fs.writeFileSync(f, x);
console.log('AndroidManifest patched');
