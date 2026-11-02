"""Runs inside AstrBot's runtime; pure policy tests also run without AstrBot."""
import copy
from collections import OrderedDict
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import unittest
from _load import load
from test_reply_limit import Event, Clock

try:
    Router = load('main').GroupMediaRouter
except ModuleNotFoundError as error:
    if not error.name.startswith(('astrbot', 'quart')): raise
    Router = None


@unittest.skipUnless(Router, 'Requires the AstrBot runtime for hook integration')
class HookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.p = object.__new__(Router)
        self.p.config = {'platform_id': 'qq', 'default_rules': {
            **copy.deepcopy(load('rules').BASE_DEFAULTS), 'chat_percent': 100,
            'reply_limit_per_minute': 1}, 'group_rules': []}
        self.p.context = SimpleNamespace(get_config=lambda **kwargs: {})
        self.p.seen = OrderedDict()
        self.p._reply_budget = load('reply_limit').ReplyWindow(Clock())
        self.counter = 0

    def event(self, at=False, group='1'):
        e = Event(group=group, route=False,
            segments=[{'type': 'at', 'data': {'qq': '99'}}] if at else None)
        self.counter += 1
        e.message_obj.message_id = str(self.counter)
        e.message_obj.timestamp = time.time()
        e.message_str = 'hello'
        e.get_sender_id = lambda: '456'
        e.result = SimpleNamespace(chain=[SimpleNamespace(text='reply')])
        e.bot = SimpleNamespace(call_action=AsyncMock(return_value={'message_id': str(self.counter)}))
        e.get_result = lambda: e.result
        e.stop_event = lambda: e.extra.update(stopped=True)
        return e

    async def prepare(self, e):
        await self.p.route(e)
        await self.p.enrich(e, SimpleNamespace(prompt='', image_urls=[]))

    async def test_successful_reply_is_counted_and_next_automatic_reply_is_skipped(self):
        first = self.event()
        await self.prepare(first)
        await self.p.enforce_reply_policy(first)
        await first.bot.send_group_msg(group_id=1, message='reply')
        await self.p.count_sent_reply(first)
        second = self.event()
        await self.p.route(second)
        self.assertTrue(second.get_extra('group_media_reply_limit_blocked'))
        self.assertFalse(second.get_extra('stopped'))  # Passive listeners still run.
        await self.p.enrich(second, SimpleNamespace())
        self.assertTrue(second.get_extra('stopped'))

    async def test_at_can_reply_when_budget_is_exhausted_and_does_not_spend_quota(self):
        for _ in range(3):
            e = self.event(at=True)
            await self.prepare(e)
            await self.p.enforce_reply_policy(e)
            # Mentions retain the original client; no budget proxy is installed.
            await e.bot.call_action('send_group_msg', group_id=1, message='reply')
            await self.p.count_sent_reply(e)
            self.assertFalse(e.get_extra('stopped'))
        regular = self.event()
        await self.prepare(regular)
        await self.p.enforce_reply_policy(regular)
        await regular.bot.send_group_msg(group_id=1, message='reply')
        await self.p.count_sent_reply(regular)
        at = self.event(at=True)
        await self.prepare(at)
        await self.p.enforce_reply_policy(at)
        self.assertFalse(at.get_extra('stopped'))

    async def test_two_in_flight_responses_cannot_send_past_limit(self):
        first, second = self.event(), self.event()
        await self.prepare(first)
        await self.prepare(second)
        await self.p.enforce_reply_policy(first)
        await self.p.enforce_reply_policy(second)
        self.assertTrue(first.result.chain)
        self.assertFalse(second.result.chain)
        self.assertTrue(second.get_extra('stopped'))

    async def test_probability_misses_and_failed_send_do_not_spend_quota(self):
        self.p.config['default_rules']['chat_percent'] = 0
        skipped = self.event()
        await self.p.route(skipped)
        await self.p.enforce_reply_policy(skipped)
        self.assertFalse(self.p._reply_window().groups)
        self.p.config['default_rules']['chat_percent'] = 100
        failed = self.event()
        await self.prepare(failed)
        await self.p.enforce_reply_policy(failed)
        await self.p.count_sent_reply(failed)
        self.assertTrue(self.p._reply_limit_available(self.event()))


if __name__ == '__main__': unittest.main()
