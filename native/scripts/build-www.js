// Copies the website files into native/www so Capacitor can wrap them in the Android app.
const fs = require('fs'), path = require('path');
const root = path.resolve(__dirname, '..', '..'), out = path.resolve(__dirname, '..', 'www');
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
for (const f of ['index.html', 'config.js', 'manifest.json', 'privacy.html', 'terms.html']) {
  if (fs.existsSync(path.join(root, f))) fs.copyFileSync(path.join(root, f), path.join(out, f));
}
for (const d of ['icons', 'images']) {
  if (fs.existsSync(path.join(root, d))) fs.cpSync(path.join(root, d), path.join(out, d), { recursive: true });
}
console.log('www ready:', fs.readdirSync(out).join(', '));
