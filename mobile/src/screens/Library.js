import React, { useCallback, useState } from 'react';
import { FlatList, Text } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { supabase } from '../supabase';
import { TrackRow } from '../ui';
import { C } from '../theme';
export default function Library() {
  const [l, setL] = useState([]);
  useFocusEffect(useCallback(() => {
    supabase.from('liked_songs').select('track').order('created_at', { ascending: false }).then(({ data }) => setL((data || []).map(x => x.track).filter(Boolean)));
  }, []));
  return <FlatList style={{ backgroundColor: C.bg }} data={l} keyExtractor={t => t.videoId} renderItem={({ item }) => <TrackRow t={item} list={l} />}
    ListEmptyComponent={<Text style={{ color: C.m, textAlign: 'center', padding: 24 }}>No liked songs yet</Text>} />;
}
