"""Count accepted OneBot sends on this event, without patching the shared client."""
from functools import partial


class ReplySendProxy:
    actions = {'send_group_msg', 'send_group_forward_msg', 'send_msg'}

    def __init__(self, router, event, bot):
        self.router = router
        self.event = event
        self.bot = bot
        self.group_id = str(event.get_group_id())

    def __getattr__(self, name):
        if name in self.actions:
            return partial(self.call_action, name)
        return getattr(self.bot, name)

    def _same_group(self, params):
        return (str(params.get('group_id', '')) == self.group_id
                and params.get('message_type', 'group') == 'group')

    async def call_action(self, action, **params):
        async def send():
            return await self.bot.call_action(action, **params)
        if action in self.actions and self._same_group(params):
            return await self.router._send_limited_reply(self.event, send)
        return await send()

    async def send(self, event, message, **params):
        async def send():
            return await self.bot.send(event, message, **params)
        target = dict(event)
        target.update(params)
        if self._same_group(target):
            return await self.router._send_limited_reply(self.event, send)
        return await send()
