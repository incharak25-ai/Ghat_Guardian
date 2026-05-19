import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Vibration, Alert } from 'react-native';

export default function SOSScreen({ route, navigation }) {
  const payload = route.params?.payload || {};
  const [etaSec, setEtaSec] = useState((payload.eta_minutes || 10) * 60);

  useEffect(() => {
    // Urgent vibration pattern — cannot be dismissed accidentally
    Vibration.vibrate([500, 200, 500, 200, 1000], true);

    const interval = setInterval(() => {
      setEtaSec(prev => Math.max(0, prev - 1));
    }, 1000);

    return () => {
      clearInterval(interval);
      Vibration.cancel();
    };
  }, []);

  const cancel = () => {
    Alert.alert(
      'Cancel SOS?',
      'Only cancel if this was a false alarm. Rescue team will be notified.',
      [
        { text: 'Keep SOS Active', style: 'cancel' },
        {
          text: 'Cancel SOS — False Alarm',
          style: 'destructive',
          onPress: () => {
            Vibration.cancel();
            navigation.goBack();
          },
        },
      ]
    );
  };

  const min = Math.floor(etaSec / 60);
  const sec = etaSec % 60;

  return (
    <View style={s.container}>

      <Text style={s.sosLabel}>🆘 SOS ACTIVE</Text>
      <Text style={s.vehicle}>{payload.vehicle_id || '---'}</Text>
      <Text style={s.trigger}>
        {payload.trigger === 'AUTO_IMU'
          ? '🤖 AUTO-DETECTED — IMU crash signature >2.5G'
          : '🔴 MANUAL SOS TRIGGERED'}
      </Text>

      {/* Crash coordinates */}
      <View style={s.coordBox}>
        <Text style={s.coordLabel}>CRASH COORDINATES</Text>
        <Text style={s.coords}>
          {payload.lat?.toFixed(5) ?? '--'}, {payload.lng?.toFixed(5) ?? '--'}
        </Text>
      </View>

      {/* Rescue ETA countdown */}
      <View style={s.etaBox}>
        <Text style={s.etaLabel}>RESCUE ETA</Text>
        <Text style={s.etaNum}>{min}:{sec.toString().padStart(2, '0')}</Text>
        <Text style={s.etaUnit}>
          {payload.nearest_unit || 'Nearest rescue unit'}
        </Text>
      </View>

      <Text style={s.notice}>
        Rescue team has been automatically notified.{'\n'}
        Stay calm and remain with the vehicle.
      </Text>

      {/* False alarm cancel — deliberately hard to press */}
      <TouchableOpacity style={s.cancelBtn} onPress={cancel}>
        <Text style={s.cancelText}>FALSE ALARM — CANCEL SOS</Text>
      </TouchableOpacity>

    </View>
  );
}

const s = StyleSheet.create({
  container:  { flex:1, backgroundColor:'#0a0000', alignItems:'center', justifyContent:'center', padding:24 },
  sosLabel:   { fontFamily:'monospace', fontSize:28, fontWeight:'900', color:'#FF0033', letterSpacing:6, marginBottom:8, textShadowColor:'#FF0033', textShadowRadius:20 },
  vehicle:    { fontFamily:'monospace', fontSize:16, color:'#d4e9f7', letterSpacing:4, marginBottom:4 },
  trigger:    { fontFamily:'monospace', fontSize:10, color:'#6a8fa8', letterSpacing:2, textAlign:'center', marginBottom:28 },
  coordBox:   { backgroundColor:'#1a0005', borderRadius:6, padding:14, width:'100%', alignItems:'center', marginBottom:16, borderWidth:1, borderColor:'#FF003344' },
  coordLabel: { fontFamily:'monospace', fontSize:9, color:'#6a8fa8', letterSpacing:4, marginBottom:4 },
  coords:     { fontFamily:'monospace', fontSize:14, color:'#FF0033', letterSpacing:2 },
  etaBox:     { alignItems:'center', marginBottom:24 },
  etaLabel:   { fontFamily:'monospace', fontSize:10, color:'#6a8fa8', letterSpacing:4, marginBottom:4 },
  etaNum:     { fontFamily:'monospace', fontSize:56, fontWeight:'900', color:'#EF9F27', lineHeight:60 },
  etaUnit:    { fontFamily:'monospace', fontSize:11, color:'#d4e9f7', letterSpacing:2, marginTop:4 },
  notice:     { fontFamily:'monospace', fontSize:11, color:'#6a8fa8', textAlign:'center', lineHeight:18, marginBottom:28 },
  cancelBtn:  { borderWidth:1, borderColor:'#2a4a5e', borderRadius:4, paddingVertical:12, paddingHorizontal:24 },
  cancelText: { fontFamily:'monospace', fontSize:11, color:'#2a4a5e', letterSpacing:3 },
});
