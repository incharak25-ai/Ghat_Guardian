import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Animated, Vibration, TouchableOpacity } from 'react-native';
import { RISK_COLORS } from '../services/api';

export default function AlertScreen({ route, navigation }) {
  const payload = route.params?.payload || {};
  const risk    = payload.risk_level || 'HIGH';
  const color   = RISK_COLORS[risk]  || RISK_COLORS.HIGH;
  const pulse   = useRef(new Animated.Value(1)).current;
  const [ttc, setTtc] = useState(
    payload.ttc_seconds ? +payload.ttc_seconds.toFixed(1) : null
  );

  useEffect(() => {
    // Vibrate on CRITICAL
    if (risk === 'CRITICAL') {
      Vibration.vibrate([200, 100, 200, 100, 500], true);
    }

    // Pulsing ring animation
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue:1.1, duration:400, useNativeDriver:true }),
        Animated.timing(pulse, { toValue:1,   duration:400, useNativeDriver:true }),
      ])
    ).start();

    // TTC countdown in 0.5s steps
    let interval;
    if (ttc) {
      interval = setInterval(() => {
        setTtc(prev => {
          if (prev === null || prev <= 0.5) { clearInterval(interval); return 0; }
          return +(prev - 0.5).toFixed(1);
        });
      }, 500);
    }

    return () => {
      Vibration.cancel();
      if (interval) clearInterval(interval);
    };
  }, []);

  return (
    <View style={s.container}>

      {/* Pulsing ring */}
      <Animated.View style={[
        s.ring,
        { borderColor: color, transform: [{ scale: pulse }] }
      ]}/>

      <Text style={[s.riskText, { color }]}>{risk}</Text>
      <Text style={s.title}>COLLISION WARNING</Text>

      {/* TTC countdown */}
      {ttc !== null && (
        <View style={s.ttcBox}>
          <Text style={[s.ttcNum, { color }]}>{ttc.toFixed(1)}s</Text>
          <Text style={s.ttcLabel}>TIME TO COLLISION</Text>
        </View>
      )}

      <Text style={s.warning}>
        {payload.warning || 'Reduce speed immediately'}
      </Text>

      {payload.v2v_alert ? (
        <Text style={s.v2v}>📡 {payload.v2v_alert}</Text>
      ) : null}

      <Text style={s.vehicle}>{payload.vehicle_id}</Text>

      <TouchableOpacity
        style={[s.ackBtn, { borderColor: color }]}
        onPress={() => { Vibration.cancel(); navigation.goBack(); }}
      >
        <Text style={[s.ackText, { color }]}>ACKNOWLEDGE</Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  container: { flex:1, backgroundColor:'#020509', alignItems:'center', justifyContent:'center', padding:24 },
  ring:      { position:'absolute', width:280, height:280, borderRadius:140, borderWidth:2, opacity:.3 },
  riskText:  { fontFamily:'monospace', fontSize:48, fontWeight:'900', letterSpacing:8, marginBottom:8 },
  title:     { fontFamily:'monospace', fontSize:14, color:'#d4e9f7', letterSpacing:5, marginBottom:24 },
  ttcBox:    { alignItems:'center', marginBottom:20 },
  ttcNum:    { fontFamily:'monospace', fontSize:64, fontWeight:'900', lineHeight:68 },
  ttcLabel:  { fontFamily:'monospace', fontSize:10, color:'#6a8fa8', letterSpacing:4 },
  warning:   { fontFamily:'monospace', fontSize:13, color:'#d4e9f7', textAlign:'center', letterSpacing:1, marginBottom:12 },
  v2v:       { fontFamily:'monospace', fontSize:11, color:'#EF9F27', textAlign:'center', marginBottom:20, paddingHorizontal:20 },
  vehicle:   { fontFamily:'monospace', fontSize:11, color:'#2a4a5e', letterSpacing:4, marginBottom:32 },
  ackBtn:    { borderWidth:1, borderRadius:4, paddingVertical:14, paddingHorizontal:40 },
  ackText:   { fontFamily:'monospace', fontWeight:'700', fontSize:13, letterSpacing:4 },
});
