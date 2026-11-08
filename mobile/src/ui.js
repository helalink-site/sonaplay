import React from 'react';
import { View, Text, Image, Pressable, ActionSheetIOS, Platform, Alert } from 'react-native';
import { C } from './theme';
import { usePlayer } from './Player';
import { supabase } from './supabase';

export const Title = ({ children }) => <Text style={{ color: C.t, fontSize: 16, fontWeight: '700', marginTop: 18, marginBottom: 8, paddingHorizontal: 16 }}>{children}</Text>;
export const Btn = ({ label, onPress, ghost, style }) => (
  <Pressable onPress={onPress} accessibilityRole="button" style={[{ padding: 14, borderRadius: 13, alignItems: 'center', backgroundColor: ghost ? C.s2 : C.v }, style]}>
    <Text style={{ color: '#fff', fontWeight: '700' }}>{label}</Text>
  </Pressable>);

async function like(t) {
  const { data: { user } } = await supabase.auth.getUser();
  const { error } = await supabase.from('liked_songs').upsert({ user_id: user.id, video_id: t.videoId, track: t });
  Alert.alert(error ? 'Could not like this song' : 'Added to liked songs');
}
async function follow(t) {
  const { data: { user } } = await supabase.auth.getUser();
  const { error } = await supabase.from('follows').upsert({ user_id: user.id, artist_name: t.artist, kind: t.isMix ? 'dj' : 'artist' });
  Alert.alert(error ? 'Could not follow' : 'Following ' + t.artist);
}
function menu(t) {
  const opts = [['Like', () => like(t)], ['Follow ' + (t.artist || 'artist'), () => follow(t)]];
  if (Platform.OS === 'ios') ActionSheetIOS.showActionSheetWithOptions({ options: [...opts.map(o => o[0]), 'Close'], cancelButtonIndex: opts.length }, i => opts[i] && opts[i][1]());
  else Alert.alert(t.title || '', undefined, [...opts.map(o => ({ text: o[0], onPress: o[1] })), { text: 'Close', style: 'cancel' }]);
}
export function TrackRow({ t, list }) {
  const { play } = usePlayer();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 6 }}>
      <Pressable onPress={() => play(t, list)} style={{ flex: 1, flexDirection: 'row', alignItems: 'center' }}>
        <Image source={{ uri: t.thumbnail }} style={{ width: t.isMix ? 96 : 54, height: 54, borderRadius: 10, backgroundColor: C.s2 }} />
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text numberOfLines={1} style={{ color: C.t, fontWeight: '600' }}>{t.title}</Text>
          <Text numberOfLines={1} style={{ color: t.isMix ? C.p : C.m, fontSize: 12 }}>{t.artist}</Text>
        </View>
      </Pressable>
      <Pressable onPress={() => menu(t)} accessibilityLabel="More options" style={{ padding: 10 }}><Text style={{ color: C.t, fontSize: 20 }}>⋯</Text></Pressable>
    </View>);
}
