import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { Alert } from 'react-native';
import { Audio } from 'expo-av';
import { streamUrl } from './api';
const Ctx = createContext(null);
export const usePlayer = () => useContext(Ctx);
export function PlayerProvider({ children }) {
  const snd = useRef(null), listRef = useRef([]), curRef = useRef(null);
  const [track, setTrack] = useState(null), [playing, setPlaying] = useState(false), [pos, setPos] = useState({ p: 0, d: 0 });
  useEffect(() => {
    Audio.setAudioModeAsync({ staysActiveInBackground: true, playsInSilentModeIOS: true, shouldDuckAndroid: true }).catch(() => {});
    return () => { snd.current && snd.current.unloadAsync(); };
  }, []);
  const next = useCallback((n = 1) => {
    const l = listRef.current; if (!l.length) return;
    const i = l.findIndex(t => t.videoId === curRef.current?.videoId);
    play(l[(i + n + l.length) % l.length], l);
  }, []);
  const play = useCallback(async (t, list) => {
    if (list) listRef.current = list;
    curRef.current = t; setTrack(t); setPos({ p: 0, d: 0 });
    try {
      if (snd.current) { await snd.current.unloadAsync(); snd.current = null; }
      const uri = await streamUrl(t.videoId, !!t.isMix);
      if (curRef.current !== t) return;               // user picked another song meanwhile
      const { sound } = await Audio.Sound.createAsync({ uri }, { shouldPlay: true }, st => {
        if (!st.isLoaded) return;
        setPlaying(st.isPlaying); setPos({ p: st.positionMillis, d: st.durationMillis || 0 });
        if (st.didJustFinish) next(1);
      });
      snd.current = sound;
    } catch (e) { Alert.alert('Could not play this song'); next(1); }
  }, [next]);
  const toggle = useCallback(async () => { const s = snd.current; if (!s) return; const st = await s.getStatusAsync(); st.isPlaying ? s.pauseAsync() : s.playAsync(); }, []);
  const seek = useCallback(ms => snd.current && snd.current.setPositionAsync(Math.max(0, ms)), []);
  const stop = useCallback(async () => { if (snd.current) { await snd.current.unloadAsync(); snd.current = null; } curRef.current = null; setTrack(null); setPlaying(false); }, []);
  return <Ctx.Provider value={{ track, playing, pos, play, toggle, seek, next, stop }}>{children}</Ctx.Provider>;
}
