# Sona Play server on a phone (Termux)
1. bash ~/sonaplay/termux-server/install.sh
2. Create ~/sona.env from env.example (values from Render > Environment). Never commit it.
3. bash ~/sonaplay/termux-server/start.sh   (leave Termux running; battery = Unrestricted)
4. Check: curl -s https://<tunnel address printed>/api/health
Switch back to Render: in Supabase run  update app_config set api_url = null where id = 1;
