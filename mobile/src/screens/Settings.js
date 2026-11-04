import React, { useEffect, useState } from 'react';
import { ScrollView, View, Text, TextInput, Pressable, Switch, Alert } from 'react-native';
import { supabase } from '../supabase';
import { usePlayer } from '../Player';
import { Btn } from '../ui';
import { C } from '../theme';
import { GENRES, API, VERSION } from '../config';
export default function Settings() {
  const { stop } = usePlayer();
  const [genres, setGenres] = useState([]), [notify, setNotify] = useState(true), [name, setName] = useState(''), [pw, setPw] = useState(''), [uid, setUid] = useState('');
  useEffect(() => { (async () => {
    const { data: { user } } = await supabase.auth.getUser(); setUid(user.id); setName(user.user_metadata?.display_name || '');
    const { data } = await supabase.from('user_prefs').select('genres,notify_new_songs').eq('user_id', user.id).maybeSingle();
    if (data) { setGenres(data.genres || []); setNotify(data.notify_new_songs !== false); }
  })(); }, []);
  const savePrefs = (g, n) => supabase.from('user_prefs').upsert({ user_id: uid, genres: g, notify_new_songs: n, updated_at: new Date().toISOString() });
  const toggleGenre = g => { const x = genres.includes(g) ? genres.filter(a => a !== g) : [...genres, g]; setGenres(x); savePrefs(x, notify); };
  async function saveProfile() {
    if (pw && pw.length < 8) return Alert.alert('Password needs at least 8 characters');
    const u = { data: { display_name: name } }; if (pw) u.password = pw;
    const { error } = await supabase.auth.updateUser(u);
    if (!error) { await supabase.from('profiles').update({ display_name: name }).eq('id', uid); setPw(''); }
    Alert.alert(error ? error.message : 'Profile updated');
  }
  async function signOut() { await stop(); await supabase.auth.signOut(); }
  function del() {
    Alert.alert('Delete account?', 'Your follows, likes and playlists are removed. This can’t be undone.', [{ text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
        const { data: { session } } = await supabase.auth.getSession();
        const r = await fetch(`${API}/account/delete`, { method: 'POST', headers: { Authorization: `Bearer ${session.access_token}` } });
        if (r.ok) { await stop(); await supabase.auth.signOut(); } else Alert.alert('Could not delete the account');
      } }]);
  }
  const box = { backgroundColor: C.s2, color: C.t, borderRadius: 12, padding: 13, marginBottom: 10 };
  return (
    <ScrollView style={{ backgroundColor: C.bg }} contentContainerStyle={{ padding: 16 }}>
      <Text style={{ color: C.t, fontWeight: '700', marginBottom: 8 }}>Profile</Text>
      <TextInput value={name} onChangeText={setName} placeholder="Display name" placeholderTextColor={C.m} style={box} />
      <TextInput value={pw} onChangeText={setPw} placeholder="New password (optional)" placeholderTextColor={C.m} secureTextEntry style={box} />
      <Btn label="Save changes" onPress={saveProfile} />
      <Text style={{ color: C.t, fontWeight: '700', marginTop: 24, marginBottom: 8 }}>Genres</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>{GENRES.map(g => (
        <Pressable key={g} onPress={() => toggleGenre(g)} style={{ paddingVertical: 8, paddingHorizontal: 14, borderRadius: 18, margin: 4, backgroundColor: genres.includes(g) ? C.v : C.s2 }}>
          <Text style={{ color: '#fff' }}>{g}</Text></Pressable>))}</View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 20 }}>
        <Text style={{ color: C.t }}>New song alerts</Text><Switch value={notify} onValueChange={v => { setNotify(v); savePrefs(genres, v); }} trackColor={{ true: C.v }} /></View>
      <Btn ghost label="Sign out" onPress={signOut} style={{ marginTop: 24 }} />
      <Btn ghost label="Delete account" onPress={del} style={{ marginTop: 10 }} />
      <Text style={{ color: C.m, textAlign: 'center', marginTop: 24 }}>{VERSION}</Text>
    </ScrollView>);
}
