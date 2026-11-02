"""Protocol sends, rather than reply turns, spend the rolling group budget."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from _load import load
import test_reply_limit as fixtures

policy = load('reply_limit')


class ProtocolSendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.router = fixtures.Subject(limit=3)
        self.router._block_reply_limit = lambda event: event.set_extra('group_media_reply_limit_blocked', True)
        self.bot = SimpleNamespace(call_action=AsyncMock(return_value={'message_id': 'accepted'}),
                                   send=AsyncMock(return_value={'message_id': 'accepted'}))

    def event(self, group='1', mention=False):
        segments = [{'type': 'at', 'data': {'qq': '99'}}] if mention else None
        event = fixtures.Event(group=group, segments=segments)
        event.bot = self.bot
        self.router._install_send_budget(event)
        return event

    async def send(self, event, text='reply'):
        return await event.bot.send_group_msg(group_id=int(event.group), message=text)

    async def test_real_burst_three_turns_with_stickers_cannot_send_five_messages(self):
        first = self.event()
        self.router._reserve_reply(first)  # Decorating-stage reservation.
        await self.send(first, 'text A')
        await self.send(first, 'sticker A')
        self.router._finish_reply(first)
        self.router.clock.value += 16
        second = self.event()
        await self.send(second, 'text B')
        self.router._finish_reply(second)
        self.router.clock.value += 18
        third = self.event()
        await self.send(third, 'text C')
        await self.send(third, 'sticker C')
        self.router._finish_reply(third)
        self.assertEqual(self.bot.call_action.await_count, 3)
        self.assertTrue(third.get_extra('group_media_reply_limit_blocked'))
        self.router.clock.value += 17
        mentioned = self.event(mention=True)
        await mentioned.bot.call_action('send_group_msg', group_id=1, message='explicit mention reply')
        self.assertEqual(self.bot.call_action.await_count, 4)
        self.assertFalse(self.router._reply_limit_available(self.event()))

    async def test_after_hook_does_not_charge_a_second_time_or_charge_unsent_result(self):
        event = self.event()
        self.router._reserve_reply(event)
        await self.send(event)
        event._has_send_oper = True
        self.router._finish_reply(event)
        bucket = self.router._reply_window().groups[('qq', '1')]
        self.assertEqual(len(bucket['sent']), 1)
        unsent = self.event()
        self.router._reserve_reply(unsent)
        unsent._has_send_oper = True
        self.router._finish_reply(unsent)
        self.assertEqual(len(bucket['sent']), 1)
        self.assertFalse(bucket['pending'])

    async def test_parallel_sends_from_one_event_have_separate_reservations(self):
        event = self.event()
        barrier = asyncio.Event()
        async def delayed(*args, **kwargs):
            await barrier.wait()
            return {'message_id': 'accepted'}
        self.bot.call_action.side_effect = delayed
        tasks = [asyncio.create_task(self.send(event, str(index))) for index in range(5)]
        await asyncio.sleep(0)
        self.assertEqual(self.bot.call_action.await_count, 3)
        barrier.set()
        await asyncio.gather(*tasks)
        self.assertEqual(len(self.router._reply_window().groups[('qq', '1')]['sent']), 3)

    async def test_failed_protocol_send_releases_only_its_own_reservation(self):
        event = self.event()
        self.bot.call_action.side_effect = RuntimeError('simulated send failure')
        with self.assertRaises(RuntimeError): await self.send(event)
        self.assertTrue(self.router._reply_limit_available(self.event()))
        self.assertFalse(self.router._reply_window().groups[('qq', '1')]['sent'])

    async def test_cancelled_protocol_send_releases_reservation(self):
        event = self.event()
        self.bot.call_action.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError): await self.send(event)
        self.assertFalse(self.router._reply_window().groups[('qq', '1')]['pending'])

    async def test_sixty_seconds_starts_when_each_message_was_accepted(self):
        event = self.event()
        await self.send(event)
        self.router.clock.value += 10
        await self.send(event)
        await self.send(event)
        self.router.clock.value += 49.999
        self.assertFalse(self.router._reply_limit_available(self.event()))
        self.router.clock.value += .001
        later = self.event()
        await self.send(later)
        self.assertEqual(self.bot.call_action.await_count, 4)
        self.assertFalse(self.router._reply_limit_available(self.event()))

    async def test_forward_and_generic_group_actions_each_spend_one_slot(self):
        event = self.event()
        await event.bot.call_action('send_group_forward_msg', group_id=1, messages=[])
        await event.bot.send_msg(message_type='group', group_id=1, message='B')
        await event.bot.send({'group_id':1, 'message_type':'group'}, 'C')
        await self.send(event, 'blocked')
        self.assertEqual(self.bot.call_action.await_count, 2)
        self.assertEqual(self.bot.send.await_count, 1)

    async def test_other_groups_private_actions_and_read_only_calls_are_independent(self):
        event = self.event()
        for _ in range(4):
            await event.bot.call_action('get_msg', message_id=123)
            await event.bot.send_group_msg(group_id=2, message='other group')
            await event.bot.call_action('send_msg', message_type='private', user_id=12, message='private')
        self.assertTrue(self.router._reply_limit_available(event))
        self.assertIsNot(self.event(group='2').bot, event.bot)
        self.assertIs(event.bot.bot, self.bot)  # Shared client was never patched.

    async def test_saving_lower_limit_applies_before_next_segment(self):
        event = self.event()
        await self.send(event)
        self.router.config['default_rules']['reply_limit_per_minute'] = 1
        await self.send(event)
        self.assertEqual(self.bot.call_action.await_count, 1)

    async def test_zero_keeps_unlimited_sends(self):
        self.router.config['default_rules']['reply_limit_per_minute'] = 0
        event = self.event()
        for _ in range(5): await self.send(event)
        self.assertEqual(self.bot.call_action.await_count, 5)
        self.assertFalse(self.router._reply_window().groups)


try:
    from astrbot.api.message_components import Plain
    from astrbot.api.event import MessageChain
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
except ModuleNotFoundError as error:
    if error.name != 'astrbot': raise
    AiocqhttpMessageEvent = None


@unittest.skipUnless(AiocqhttpMessageEvent, 'Requires AstrBot for real adapter integration')
class AdapterSendTests(unittest.IsolatedAsyncioTestCase):
    setUp = ProtocolSendTests.setUp
    event = ProtocolSendTests.event

    async def test_actual_adapter_segments_count_each_qq_message(self):
        event = self.event()
        for text in ['A', 'B', 'C', 'D']:
            await AiocqhttpMessageEvent.send_message(event.bot, MessageChain([Plain(text)]),
                is_group=True, session_id='1')
        self.assertEqual(self.bot.call_action.await_count, 3)

    async def test_combined_components_are_one_qq_message(self):
        event = self.event()
        await AiocqhttpMessageEvent.send_message(event.bot, MessageChain([Plain('A'), Plain('B')]),
            is_group=True, session_id='1')
        self.assertEqual(self.bot.call_action.await_count, 1)
        self.assertEqual(len(self.router._reply_window().groups[('qq', '1')]['sent']), 1)


if __name__ == '__main__': unittest.main()
