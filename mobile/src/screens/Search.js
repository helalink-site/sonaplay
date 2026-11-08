import React, { useEffect, useState } from 'react';
import { View, TextInput, FlatList, Text } from 'react-native';
import { search } from '../api';
import { TrackRow } from '../ui';
import { C } from '../theme';
export default function Search() {
  const [q, setQ] = useState(''), [r, setR] = useState([]), [done, setDone] = useState(false);
  useEffect(() => {                                  // 300 ms debounce
    if (q.trim().length < 2) { setR([]); setDone(false); return; }
    const h = setTimeout(async () => { try { setR(await search(q.trim(), 20)); } catch (e) { setR([]); } setDone(true); }, 300);
    return () => clearTimeout(h);
  }, [q]);
  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      <TextInput value={q} onChangeText={setQ} placeholder="Search official songs and artists" placeholderTextColor={C.m}
        style={{ backgroundColor: C.s2, color: C.t, margin: 14, borderRadius: 14, padding: 13 }} />
      <FlatList data={r} keyExtractor={t => t.videoId} renderItem={({ item }) => <TrackRow t={item} list={r} />}
        ListEmptyComponent={done ? <Text style={{ color: C.m, textAlign: 'center', padding: 24 }}>No results</Text> : null} />
    </View>);
}
