import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, StatusBar } from 'react-native';
import MapView, { Marker, Polyline, Circle } from 'react-native-maps';
import ws from '../services/websocket';
import { RISK_COLORS } from '../services/api';

const NH75 = [
  {latitude:12.9716,longitude:77.5946},
  {latitude:13.0979,longitude:77.3952},
  {latitude:13.0210,longitude:77.0253},
  {latitude:13.0050,longitude:76.1000},
  {latitude:12.9420,longitude:75.7850},
  {latitude:12.7500,longitude:75.6800},
  {latitude:12.9579,longitude:75.3750},
];

const DARK_MAP_STYLE = [
  {elementType:'geometry',stylers:[{color:'#0a1520'}]},
  {elementType:'labels.text.fill',stylers:[{color:'#4a7a9b'}]},
  {featureType:'road',elementType:'geometry',stylers:[{color:'#0d2535'}]},
  {featureType:'water',elementType:'geometry',stylers:[{color:'#020509'}]},
];

export default function MapScreen({ route, navigation }) {
  const { vehicleId } = route.params;
  const [vehicles,  setVehicles]  = useState({});
  const [myData,    setMyData]    = useState(null);
  const [connected, setConnected] = useState(false);
  const mapRef = useRef(null);

  useEffect(() => {
    const unsubs = [
      ws.on('connected',    ()  => setConnected(true)),
      ws.on('disconnected', ()  => setConnected(false)),
      ws.on('telemetry',    (p) => {
        setVehicles(prev => ({ ...prev, [p.vehicle_id]: p }));
        if (p.vehicle_id === vehicleId) {
          setMyData(p);
          if (['HIGH', 'CRITICAL'].includes(p.risk_level)) {
            navigation.navigate('Alert', { payload: p });
          }
          if (p.sos_active) {
            navigation.navigate('SOS', { payload: p });
          }
        }
      }),
      ws.on('snapshot', (p) => {
        const map = {};
        p.vehicles?.forEach(v => { map[v.vehicle_id] = v; });
        setVehicles(map);
      }),
    ];
    return () => unsubs.forEach(u => u());
  }, [vehicleId]);

  const risk  = myData?.risk_level || 'LOW';
  const color = RISK_COLORS[risk]  || RISK_COLORS.LOW;
  const speed = myData?.speed?.toFixed(0) || '0';

  return (
    <View style={s.container}>
      <StatusBar barStyle="light-content" backgroundColor="#020509"/>

      {/* HUD header */}
      <View style={s.hud}>
        <View>
          <Text style={s.vehicleId}>{vehicleId}</Text>
          <Text style={[s.riskBadge, {color, borderColor: color}]}>{risk}</Text>
        </View>
        <View style={s.speedBox}>
          <Text style={s.speedNum}>{speed}</Text>
          <Text style={s.speedUnit}>km/h</Text>
        </View>
        <View style={{alignItems:'flex-end'}}>
          <Text style={[s.wsStatus, {color: connected ? RISK_COLORS.LOW : RISK_COLORS.MEDIUM}]}>
            {connected ? '● LIVE' : '◌ DEMO'}
          </Text>
          <Text style={s.fogText}>FOG {myData?.fog_visibility?.toFixed(0) ?? '--'}%</Text>
        </View>
      </View>

      {/* Map */}
      <MapView
        ref={mapRef}
        style={s.map}
        customMapStyle={DARK_MAP_STYLE}
        initialRegion={{ latitude:12.97, longitude:77.59, latitudeDelta:3, longitudeDelta:3 }}
        showsUserLocation={false}
      >
        <Polyline coordinates={NH75} strokeColor="#00b4d8" strokeWidth={2} lineDashPattern={[8,4]}/>

        {/* Shiradi Ghat black spot */}
        <Circle
          center={{latitude:12.75, longitude:75.68}}
          radius={3000}
          strokeColor={RISK_COLORS.CRITICAL}
          fillColor="rgba(185,28,28,0.1)"
          strokeWidth={1}
        />

        {/* All vehicle markers */}
        {Object.values(vehicles).map(v => (
          <Marker key={v.vehicle_id}
            coordinate={{latitude: v.lat, longitude: v.lng}}
            anchor={{x:.5, y:.5}}
          >
            <View style={[
              s.markerDot,
              {
                backgroundColor: RISK_COLORS[v.risk_level] || RISK_COLORS.LOW,
                borderColor:     v.vehicle_id === vehicleId ? '#fff' : 'transparent',
                borderWidth:     v.vehicle_id === vehicleId ? 2 : 0,
              }
            ]}/>
          </Marker>
        ))}
      </MapView>

      {/* Warning bar */}
      {myData?.warning ? (
        <View style={[s.warnBar, {backgroundColor: color+'22', borderColor: color}]}>
          <Text style={[s.warnText, {color}]}>{myData.warning}</Text>
        </View>
      ) : null}

      {/* V2V alert bar */}
      {myData?.v2v_alert ? (
        <View style={s.v2vBar}>
          <Text style={s.v2vText}>📡 {myData.v2v_alert}</Text>
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  container:  { flex:1, backgroundColor:'#020509' },
  hud:        { flexDirection:'row', justifyContent:'space-between', alignItems:'center', padding:12, backgroundColor:'#060d14', borderBottomWidth:1, borderBottomColor:'#0d2535' },
  vehicleId:  { fontFamily:'monospace', fontWeight:'700', fontSize:14, color:'#00b4d8', letterSpacing:3 },
  riskBadge:  { fontFamily:'monospace', fontSize:9, borderWidth:1, borderRadius:3, paddingHorizontal:5, paddingVertical:2, letterSpacing:2, marginTop:3, textAlign:'center' },
  speedBox:   { alignItems:'center' },
  speedNum:   { fontFamily:'monospace', fontSize:36, fontWeight:'900', color:'#d4e9f7', lineHeight:38 },
  speedUnit:  { fontFamily:'monospace', fontSize:10, color:'#6a8fa8', letterSpacing:2 },
  wsStatus:   { fontFamily:'monospace', fontSize:10, letterSpacing:2 },
  fogText:    { fontFamily:'monospace', fontSize:10, color:'#6a8fa8', marginTop:3, letterSpacing:2 },
  map:        { flex:1 },
  markerDot:  { width:14, height:14, borderRadius:7 },
  warnBar:    { position:'absolute', bottom:60, left:12, right:12, borderRadius:4, borderWidth:1, padding:10 },
  warnText:   { fontFamily:'monospace', fontSize:12, fontWeight:'700', textAlign:'center', letterSpacing:1 },
  v2vBar:     { position:'absolute', bottom:12, left:12, right:12, backgroundColor:'rgba(239,159,39,.15)', borderRadius:4, borderWidth:1, borderColor:'#EF9F27', padding:8 },
  v2vText:    { fontFamily:'monospace', fontSize:11, color:'#EF9F27' },
});
