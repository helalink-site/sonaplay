import React, { useEffect, useState } from 'react';
import { FlatList, ActivityIndicator, Text } from 'react-native';
import { mixes } from '../api';
import { TrackRow } from '../ui';
import { C } from '../theme';
export default function Mixes() {
  const [m, setM] = useState(null);
  useEffect(() => { mixes().then(r => setM(r.map(t => ({ ...t, isMix: true })))).catch(() => setM([])); }, []);
  if (!m) return <ActivityIndicator style={{ flex: 1 }} color={C.v} />;
  return <FlatList style={{ backgroundColor: C.bg }} data={m} keyExtractor={t => t.videoId} renderItem={({ item }) => <TrackRow t={item} list={m} />}
    ListEmptyComponent={<Text style={{ color: C.m, textAlign: 'center', padding: 24 }}>No mixes found right now</Text>} />;
}
