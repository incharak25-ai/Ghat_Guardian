import json

from channels.generic.websocket import AsyncWebsocketConsumer


class TelemetryConsumer(AsyncWebsocketConsumer):

    async def connect(self):

        await self.channel_layer.group_add(
            "telemetry",
            self.channel_name
        )

        await self.accept()

        print("WEBSOCKET CONNECTED")


    async def disconnect(self, close_code):

        await self.channel_layer.group_discard(
            "telemetry",
            self.channel_name
        )

        print("WEBSOCKET DISCONNECTED")


    async def receive(self, text_data):

        try:

            print("RECEIVED:", text_data)

            data = json.loads(text_data)

            await self.channel_layer.group_send(
                "telemetry",
                {
                    "type": "telemetry_message",
                    "message": data
                }
            )

        except Exception as e:

            print("RECEIVE ERROR:", e)


    async def telemetry_message(self, event):

        try:

            message = event["message"]

            await self.send(
                text_data=json.dumps(message)
            )

        except Exception as e:

            print("SEND ERROR:", e)