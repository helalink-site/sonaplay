import React, { useState } from 'react';
import { View, Text } from 'react-native';
import { Picker } from '@react-native-picker/picker';
import { supabase } from '../supabase';
import { Btn } from '../ui';
import { C } from '../theme';
import { REGIONS } from '../config';
export default function RegionGate({ userId, onDone }) {
  const [r, setR] = useState(''), [err, setErr] = useState('');
  async function save() {
    if (!r) return setErr('Select your region');
    const a = await supabase.auth.updateUser({ data: { region: r } });
    const b = await supabase.from('profiles').update({ region: r }).eq('id', userId);
    if (a.error || b.error) return setErr('Could not save, try again');
    onDone();
  }
  return (
    <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: 'center', padding: 24 }}>
      <Text style={{ color: C.t, fontSize: 20, fontWeight: '700', marginBottom: 14 }}>Where are you listening from?</Text>
      <View style={{ backgroundColor: C.s2, borderRadius: 12, marginBottom: 14 }}><Picker selectedValue={r} onValueChange={setR} dropdownIconColor={C.t} style={{ color: C.t }}>
        <Picker.Item label="Select your region" value="" />{REGIONS.map(x => <Picker.Item key={x} label={x} value={x} />)}</Picker></View>
      {!!err && <Text style={{ color: C.p, marginBottom: 10 }}>{err}</Text>}
      <Btn label="Continue" onPress={save} />
    </View>);
}
