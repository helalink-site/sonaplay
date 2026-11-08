import React, { useState } from 'react';
import { View, Text, TextInput, KeyboardAvoidingView, Platform, ScrollView } from 'react-native';
import { Picker } from '@react-native-picker/picker';
import { supabase } from '../supabase';
import { Btn } from '../ui';
import { C } from '../theme';
import { REGIONS } from '../config';
const input = { backgroundColor: C.s2, color: C.t, borderRadius: 12, padding: 14, marginBottom: 10 };
export default function Auth() {
  const [up, setUp] = useState(false), [name, setName] = useState(''), [email, setEmail] = useState(''), [pass, setPass] = useState(''), [region, setRegion] = useState(''), [msg, setMsg] = useState(''), [busy, setBusy] = useState(false);
  async function submit() {
    setMsg('');
    if (!email || !pass) return setMsg('Enter email and password');
    if (up && !region) return setMsg('Select your region');
    if (up && pass.length < 8) return setMsg('Password needs at least 8 characters');
    setBusy(true);
    const r = up
      ? await supabase.auth.signUp({ email: email.trim(), password: pass, options: { data: { display_name: name || email.split('@')[0], region } } })
      : await supabase.auth.signInWithPassword({ email: email.trim(), password: pass });
    setBusy(false);
    if (r.error) return setMsg(r.error.message);
    if (up && !r.data.session) { setMsg('Check your email to confirm your account, then log in.'); setUp(false); }
  }
  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, backgroundColor: C.bg }}>
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: 24 }}>
        <Text style={{ color: C.v, fontSize: 34, fontWeight: '800', textAlign: 'center', marginBottom: 24 }}>Sona Play</Text>
        {up && <TextInput placeholder="Display name" placeholderTextColor={C.m} value={name} onChangeText={setName} style={input} />}
        {up && <View style={[input, { padding: 0 }]}><Picker selectedValue={region} onValueChange={setRegion} dropdownIconColor={C.t} style={{ color: C.t }}>
          <Picker.Item label="Select your region" value="" />{REGIONS.map(r => <Picker.Item key={r} label={r} value={r} />)}</Picker></View>}
        <TextInput placeholder="Email" placeholderTextColor={C.m} autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} style={input} />
        <TextInput placeholder="Password" placeholderTextColor={C.m} secureTextEntry value={pass} onChangeText={setPass} style={input} />
        {!!msg && <Text style={{ color: C.p, marginBottom: 10 }}>{msg}</Text>}
        <Btn label={busy ? 'Please wait…' : up ? 'Sign up' : 'Log in'} onPress={submit} />
        <Text onPress={() => { setUp(!up); setMsg(''); }} style={{ color: C.m, textAlign: 'center', marginTop: 18 }}>
          {up ? 'Already have an account? ' : 'New to Sona Play? '}<Text style={{ color: C.v, fontWeight: '700' }}>{up ? 'Log in' : 'Create account'}</Text></Text>
      </ScrollView>
    </KeyboardAvoidingView>);
}
