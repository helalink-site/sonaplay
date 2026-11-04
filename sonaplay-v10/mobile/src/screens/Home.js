import React, { useEffect, useState } from 'react';
import { ScrollView, ActivityIndicator, View, Text, RefreshControl } from 'react-native';
import { search } from '../api';
import { supabase } from '../supabase';
import { Title, TrackRow } from '../ui';
import { C } from '../theme';
export default function Home() {
  const [d, setD] = useState(null), [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      const [{ data: pr }, { data: fl }] = await Promise.all([
        supabase.from('user_prefs').select('genres').eq('user_id', user.id).maybeSingle(),
        supabase.from('follows').select('artist_name').eq('user_id', user.id).limit(6)]);
      const g = (pr && pr.genres) || [], g1 = g[0] || 'Afrobeats', g2 = g[1] || 'Bongo Flava';
      const foryou = fl && fl.length ? fl.map(f => `${f.artist_name} official audio`) : [`${g1} hits`, `${g2} hits`];
      const [n, t, f] = await Promise.all([search(`${g1} 2026 new release`, 6), search(`${g2} trending`, 6), Promise.all(foryou.map(q => search(q, 3))).then(a => a.flat())]);
      setD({ n, t, f });
    } catch (e) { setD({ n: [], t: [], f: [] }); }
    setBusy(false);
  }
  useEffect(() => { load(); }, []);
  if (!d) return <ActivityIndicator style={{ flex: 1 }} color={C.v} />;
  return (
    <ScrollView style={{ backgroundColor: C.bg }} refreshControl={<RefreshControl refreshing={busy} onRefresh={load} tintColor={C.v} />}>
      <Title>New releases</Title>{d.n.map(t => <TrackRow key={t.videoId} t={t} list={d.n} />)}
      <Title>Trending</Title>{d.t.map(t => <TrackRow key={t.videoId} t={t} list={d.t} />)}
      <Title>For you</Title>{d.f.map(t => <TrackRow key={t.videoId} t={t} list={d.f} />)}
      {!d.n.length && !d.t.length && <Text style={{ color: C.m, textAlign: 'center', padding: 24 }}>Nothing to show right now. Pull down to retry.</Text>}
      <View style={{ height: 24 }} />
    </ScrollView>);
}
