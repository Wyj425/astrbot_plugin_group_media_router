"""Companion stickers use Context.send_message after the main reply was sent."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from _load import load
import test_reply_limit as fixtures

guard_module = load('context_send')


class ContextSendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.router = fixtures.Subject(limit=3)
        self.router._block_reply_limit = lambda event: event.set_extra('group_media_reply_limit_blocked', True)
        self.raw_bot = SimpleNamespace(call_action=AsyncMock(return_value={'message_id':'accepted'}))
        self.context = SimpleNamespace(send_message=AsyncMock(return_value=True),
            get_config=lambda **kwargs: {'provider_ltm_settings':{'group_message_history_enable':True}},
            message_history_manager=SimpleNamespace(insert_message_chain=AsyncMock()))
        self.original = self.context.send_message
        self.router.context = self.context
        self.current = None
        self.guard = guard_module.ContextReplySender(self.router, lambda:self.current)
        self.guard.install()

    def event(self, mention=False, group='1'):
        event = fixtures.Event(group=group, segments=[{'type':'at','data':{'qq':'99'}}] if mention else None)
        event._execution_active = True
        event.bot = self.raw_bot
        self.router._install_send_budget(event)
        async def send(chain):
            await event.bot.call_action('send_group_msg', group_id=int(group), message=chain)
        event.send = send
        return event

    async def test_after_hook_sticker_and_main_text_share_actual_message_quota(self):
        self.current = first = self.event()
        await first.send('text A')
        self.router._finish_reply(first)
        self.assertTrue(await self.context.send_message(first.unified_msg_origin, 'sticker A'))
        self.current = second = self.event()
        await second.send('text B')
        self.router._finish_reply(second)
        self.assertFalse(await self.context.send_message(second.unified_msg_origin, 'sticker B'))
        self.assertEqual(self.raw_bot.call_action.await_count, 3)
        self.original.assert_not_awaited()
        self.assertEqual(self.context.message_history_manager.insert_message_chain.await_count, 1)

    async def test_unrelated_sessions_and_background_outreach_use_original_sender(self):
        self.current = event = self.event()
        await self.context.send_message('qq:GroupMessage:2', 'other group')
        self.current = None
        await self.context.send_message(event.unified_msg_origin, 'scheduled outreach')
        self.current = event
        event._execution_active = False
        await self.context.send_message(event.unified_msg_origin, 'background task after event ended')
        self.assertEqual(self.original.await_count, 3)
        self.raw_bot.call_action.assert_not_awaited()

    async def test_at_reply_companion_stickers_keep_their_exemption(self):
        self.current = event = self.event(mention=True)
        for _ in range(5): await self.context.send_message(event.unified_msg_origin, 'mention sticker')
        self.assertEqual(self.original.await_count, 5)
        self.assertFalse(self.router._reply_window().groups)

    async def test_failed_extra_sticker_is_not_counted_or_recorded(self):
        self.current = event = self.event()
        self.raw_bot.call_action.side_effect = RuntimeError('simulated send failure')
        with self.assertRaises(RuntimeError):
            await self.context.send_message(event.unified_msg_origin, 'sticker')
        self.assertTrue(self.router._reply_limit_available(self.event()))
        self.context.message_history_manager.insert_message_chain.assert_not_awaited()

    async def test_unload_restores_sender_and_detached_wrapper_stays_inactive(self):
        self.current = event = self.event()
        detached = self.context.send_message
        self.guard.remove()
        self.assertIs(self.context.send_message, self.original)
        await detached(event.unified_msg_origin, 'after unload')
        self.original.assert_awaited_once()

    async def test_nested_wrapper_keeps_other_plugin_sender_on_unload(self):
        self.current = event = self.event()
        guarded = self.context.send_message
        async def later_wrapper(session, chain): return await guarded(session, chain)
        self.context.send_message = later_wrapper
        self.guard.remove()
        self.assertIs(self.context.send_message, later_wrapper)
        await later_wrapper(event.unified_msg_origin, 'after unload')
        self.original.assert_awaited_once()


if __name__ == '__main__': unittest.main()
