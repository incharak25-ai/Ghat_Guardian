// App.js — Ghat-Guardian Driver App Entry Point
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import { StatusBar } from 'react-native';

import LoginScreen   from './screens/LoginScreen';
import MapScreen     from './screens/MapScreen';
import AlertScreen   from './screens/AlertScreen';
import SOSScreen     from './screens/SOSScreen';

const Stack = createStackNavigator();

export default function App() {
  return (
    <NavigationContainer theme={{ colors: { background: '#020509' } }}>
      <StatusBar barStyle="light-content" backgroundColor="#020509"/>
      <Stack.Navigator
        initialRouteName="Login"
        screenOptions={{
          headerShown:       false,
          cardStyle:         { backgroundColor: '#020509' },
          animationEnabled:  true,
        }}
      >
        <Stack.Screen name="Login" component={LoginScreen}/>
        <Stack.Screen name="Map"   component={MapScreen}/>
        <Stack.Screen name="Alert" component={AlertScreen}
          options={{ presentation: 'modal' }}/>
        <Stack.Screen name="SOS"   component={SOSScreen}
          options={{ presentation: 'fullScreenModal', gestureEnabled: false }}/>
      </Stack.Navigator>
    </NavigationContainer>
  );
}
