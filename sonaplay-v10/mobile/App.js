import 'react-native-url-polyfill/auto';
import React, { useEffect, useState } from 'react';
import { View, Text, Pressable, Image, ActivityIndicator } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { createBottomTabNavigator, BottomTabBar } from '@react-navigation/bottom-tabs';
import { supabase } from './src/supabase';
import { PlayerProvider, usePlayer } from './src/Player';
import { C } from './src/theme';
import Auth from './src/screens/Auth';
import RegionGate from './src/screens/RegionGate';
import Home from './src/screens/Home';
import Search from './src/screens/Search';
import Mixes from './src/screens/Mixes';
import Library from './src/screens/Library';
import Settings from './src/screens/Settings';
const Tab = createBottomTabNavigator();
const theme = { ...DarkTheme, colors: { ...DarkTheme.colors, background: C.bg, card: C.s1, primary: C.p, text: C.t, border: C.s2 } };

function Mini() {
  const { track, playing, toggle, next, pos } = usePlayer();
  if (!track) return null;
  const pct = pos.d ? (pos.p / pos.d) * 100 : 0;
  return (
    <View style={{ backgroundColor: C.s2, marginHorizontal: 8, marginBottom: 4, borderRadius: 14, overflow: 'hidden' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', padding: 8 }}>
        <Image source={{ uri: track.thumbnail }} style={{ width: 42, height: 42, borderRadius: 8, backgroundColor: C.s1 }} />
        <View style={{ flex: 1, marginHorizontal: 10 }}>
          <Text numberOfLines={1} style={{ color: C.t, fontWeight: '600' }}>{track.title}</Text>
          <Text numberOfLines={1} style={{ color: C.m, fontSize: 12 }}>{track.artist}</Text></View>
        <Pressable onPress={toggle} accessibilityLabel="Play or pause" style={{ padding: 10 }}><Text style={{ color: C.t, fontSize: 20 }}>{playing ? '❚❚' : '▶'}</Text></Pressable>
        <Pressable onPress={() => next(1)} accessibilityLabel="Next" style={{ padding: 10 }}><Text style={{ color: C.t, fontSize: 20 }}>⏭</Text></Pressable>
      </View>
      <View style={{ height: 3, backgroundColor: C.s1 }}><View style={{ height: 3, width: pct + '%', backgroundColor: C.p }} /></View>
    </View>);
}

function Tabs() {
  const screen = { headerStyle: { backgroundColor: C.bg }, headerTitleStyle: { color: C.t }, tabBarActiveTintColor: C.p, tabBarInactiveTintColor: C.m };
  return (
    <Tab.Navigator screenOptions={screen} tabBar={p => <View><Mini /><BottomTabBar {...p} /></View>}>
      <Tab.Screen name="Sona Play" component={Home} options={{ tabBarLabel: 'Home' }} />
      <Tab.Screen name="Search" component={Search} />
      <Tab.Screen name="DJ Mixes" component={Mixes} />
      <Tab.Screen name="Library" component={Library} />
      <Tab.Screen name="Settings" component={Settings} />
    </Tab.Navigator>);
}

export default function App() {
  const [session, setSession] = useState(undefined), [needRegion, setNeedRegion] = useState(false);
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);
  useEffect(() => {
    if (!session) return;
    supabase.rpc('touch_activity').then(() => {}, () => {});
    const r = session.user.user_metadata && session.user.user_metadata.region;
    if (r) return setNeedRegion(false);
    supabase.from('profiles').select('region').eq('id', session.user.id).maybeSingle().then(({ data }) => setNeedRegion(!(data && data.region)));
  }, [session && session.user.id]);
  if (session === undefined) return <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: 'center' }}><ActivityIndicator color={C.v} /></View>;
  return (
    <PlayerProvider>
      <StatusBar style="light" />
      {!session ? <Auth /> : needRegion ? <RegionGate userId={session.user.id} onDone={() => setNeedRegion(false)} /> : <NavigationContainer theme={theme}><Tabs /></NavigationContainer>}
    </PlayerProvider>);
}
