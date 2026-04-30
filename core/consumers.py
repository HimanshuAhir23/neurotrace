from channels.generic.websocket import AsyncWebsocketConsumer
import json


class DashboardConsumer(AsyncWebsocketConsumer):

    GROUP_NAME = "dashboard"

    async def connect(self):
        self.group_name = self.GROUP_NAME

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

        # Confirm connection to the client
        await self.send(text_data=json.dumps({
            "type":    "connection",
            "message": "Dashboard connected 🚀"
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """
        Dashboard is read-only — no writes accepted from the browser.
        If future two-way communication is needed, handle here.
        """
        pass

    # -----------------------------------------------
    # BROADCAST HANDLER
    # type must match the "type" key in group_send()
    # i.e. "update" → update()
    # -----------------------------------------------
    async def update(self, event):
        data = event.get("data", {})

        # FIX: wrap send in try/except so one bad client
        #      can't kill the entire consumer
        try:
            await self.send(text_data=json.dumps({
                "type": "update",
                "data": {
                    "url":        data.get("url", ""),
                    "event_type": data.get("event_type", ""),
                    "category":   data.get("category", "neutral"),
                    "log_id":     data.get("log_id", None),
                    "duration":   data.get("duration", 0),
                    "timestamp":  data.get("timestamp", ""),
                }
            }))
        except Exception as e:
            print(f"[Consumer] send failed: {e}")