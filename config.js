/* Public, browser-safe settings only. NEVER put the Supabase service_role key here.
   New Supabase project: Dashboard > Settings > API > copy Project URL and the anon (public) key. */
window.SONA_CONFIG={
  API:'https://sonaplay.onrender.com/api',
  SUPA_URL:'https://ioukidprmfvkkoohlpmy.supabase.co',
  SUPA_ANON_KEY:'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlvdWtpZHBybWZ2a2tvb2hscG15Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY0NjAxODEsImV4cCI6MjEwMjAzNjE4MX0.BMrmsC_DMDX8HP7CMyJ3O3EUOC8IWAvbBk7rE5o4wIA'
  ,VAPID_PUBLIC:'BEAnpR9WBrP5qFF2L63Mgn_dY7P8qq2Ec7M5KHrTc0OUm76SjyEnon4ZDt3qTw_sO69lGeqWueXHm1D6tJonHcY' // web push public key (npx web-push generate-vapid-keys); the private key goes on Render
};
