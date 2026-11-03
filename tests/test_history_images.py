import asyncio
import base64
import importlib.util
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock
import unittest
from _load import load

h = load('history_images')


def picture(mid, at, *, group='1', sender='10', file=None, sub_type=0, url=None):
    return {'group_id': group, 'message_id': str(mid), 'time': at, 'message_seq': int(mid),
            'user_id': sender, 'sender': {'nickname': 'member-'+sender},
            'message': [{'type': 'image', 'data': {'file': file or str(mid)+'.jpg',
                         'url': url or 'https://gchat.qpic.cn/photo/'+str(mid), 'sub_type': sub_type}}]}


def plain(mid, at, text='context'):
    return {'group_id': '1', 'message_id': str(mid), 'time': at, 'message_seq': int(mid),
            'user_id': '10', 'sender': {'nickname': 'member'},
            'message': [{'type': 'text', 'data': {'text': text}}]}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = h.options({'history_images': {'enabled': True}})

    def choose(self, messages, **kwargs):
        values = {'group_id': '1', 'trigger_id': '100', 'trigger_at': 10000,
                  'self_id': '99', 'settings': self.settings}
        values.update(kwargs)
        return h.select_images(messages, **values)

    def test_recent_thirty_messages_are_counted_before_image_filter(self):
        rows = [picture(1, 9900)]+[plain(i, 9900+i) for i in range(2, 32)]+[plain(100, 10000)]
        self.assertEqual(self.choose(rows), [])
        rows[-2] = picture(31, 9931)
        self.assertEqual([x.message_id for x in self.choose(rows)], ['31'])

    def test_trigger_and_later_messages_are_not_reintroduced_as_history(self):
        rows = [picture(1, 9998), picture(100, 10000), picture(101, 10001)]
        self.assertEqual([x.message_id for x in self.choose(rows)], ['1'])

    def test_missing_anchor_rejects_same_second_or_future_images(self):
        rows = [picture(1, 9999), picture(2, 10000), picture(3, 10001)]
        self.assertEqual([x.message_id for x in self.choose(rows)], ['1'])

    def test_other_groups_bot_stickers_and_old_images_are_excluded(self):
        rows = [picture(1, 1), picture(2, 9990, group='2'), picture(3, 9991, sender='99'),
                picture(4, 9992, sub_type=1), picture(5, 9993), plain(100, 10000)]
        self.assertEqual([x.message_id for x in self.choose(rows)], ['5'])

    def test_maximum_prefers_newest_unique_images_and_returns_chronological_order(self):
        rows = [picture(i, 9980+i) for i in range(1, 8)]+[plain(100, 10000)]
        self.assertEqual([x.message_id for x in self.choose(rows)], ['4', '5', '6', '7'])

    def test_duplicate_file_and_expiring_url_tokens_do_not_multiply_images(self):
        one = 'https://multimedia.nt.qq.com.cn/download?fileid=abc&rkey=old'
        two = 'https://multimedia.nt.qq.com.cn/download?rkey=new&fileid=abc'
        self.assertEqual(h.url_key(one), h.url_key(two))
        rows = [picture(1, 9990, file='same.jpg', url=one), picture(2, 9991, file='same.jpg', url=two), plain(100, 10000)]
        self.assertEqual(len(self.choose(rows)), 1)
        self.assertEqual(self.choose(rows, excluded_urls=[one]), [])

    def test_quoted_original_image_and_current_image_budget_are_respected(self):
        rows = [picture(i, 9990+i) for i in range(1, 5)]+[plain(100, 10000)]
        self.assertEqual([x.message_id for x in self.choose(rows, excluded_ids=['4'], slots=1)], ['3'])
        self.assertEqual(self.choose(rows, slots=0), [])

    def test_sender_and_nearby_text_are_kept_as_image_evidence(self):
        rows = [picture(1, 9990), plain(2, 9991, '土豆兄弟更新DLC了'), plain(100, 10000, '左边一列是什么')]
        result = self.choose(rows)
        self.assertEqual(result[0].sender, 'member-10')
        self.assertIn('土豆兄弟', result[0].nearby)
        self.assertNotIn('左边一列', result[0].nearby)

    def test_url_allowlist_rejects_internal_paths_ports_and_disguised_hosts(self):
        for url in ['file:///etc/passwd', 'http://127.0.0.1/a', 'https://gchat.qpic.cn.evil.test/a',
                    'https://user:password@gchat.qpic.cn/a', 'https://gchat.qpic.cn:444/a']:
            self.assertFalse(h.approved_url(url), url)
        self.assertTrue(h.approved_url('https://multimedia.nt.qq.com.cn/download?fileid=a&rkey=b'))

    def test_settings_are_opt_in_and_invalid_values_are_bounded(self):
        self.assertFalse(h.options({})['enabled'])
        settings = h.options({'history_images': {'enabled': True, 'message_limit': 999999,
                           'max_images': -4, 'max_side': 'invalid', 'cache_minutes': True}})
        self.assertEqual(settings['message_limit'], 100)
        self.assertEqual(settings['max_images'], 1)
        self.assertEqual(settings['max_side'], 1280)
        self.assertEqual(settings['cache_minutes'], 15)


PIL_AVAILABLE = importlib.util.find_spec('PIL') is not None


@unittest.skipUnless(PIL_AVAILABLE, 'Pillow is supplied by the AstrBot runtime')
class ImageTests(unittest.IsolatedAsyncioTestCase):
    def raw(self, size=(2000, 800), color='white'):
        from PIL import Image
        data = io.BytesIO()
        Image.new('RGB', size, color).save(data, 'PNG')
        return data.getvalue()

    async def test_image_is_downscaled_and_bounded(self):
        from PIL import Image
        result = h.thumbnail(self.raw(), 1280)
        raw = base64.b64decode(result.split(',', 1)[1])
        self.assertLessEqual(len(raw), h.MAX_THUMBNAIL)
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.size, (1280, 512))

    async def test_download_and_compression_are_reused_across_concurrent_requests(self):
        loader = AsyncMock(return_value=self.raw())
        cache = h.ImageCache(loader=loader)
        candidate = h.Candidate('1', '1::file:image', 'https://gchat.qpic.cn/a', 'image', 9990, 'member', '')
        one, two = await asyncio.gather(cache.get(candidate, 1280, 900), cache.get(candidate, 1280, 900))
        self.assertEqual(one, two)
        self.assertEqual(loader.await_count, 1)
        self.assertEqual(await cache.get(candidate, 1280, 900), one)
        self.assertEqual(loader.await_count, 1)
        await cache.close()

    async def test_expired_cache_fetches_again_and_failures_do_not_poison_cache(self):
        now = [1]
        loader = AsyncMock(side_effect=[ValueError('expired'), self.raw(), self.raw()])
        cache = h.ImageCache(loader=loader, clock=lambda: now[0])
        candidate = h.Candidate('1', '1::file:image', 'https://gchat.qpic.cn/a', 'image', 9990, 'member', '')
        with self.assertRaises(ValueError):
            await cache.get(candidate, 1280, 2)
        await cache.get(candidate, 1280, 2)
        now[0] = 5
        await cache.get(candidate, 1280, 2)
        self.assertEqual(loader.await_count, 3)
        await cache.close()

    async def test_oversize_or_invalid_data_is_rejected(self):
        with self.assertRaises(ValueError):
            h.thumbnail(b'x'*(h.MAX_DOWNLOAD+1), 1280)
        with self.assertRaises(Exception):
            h.thumbnail(b'not an image', 1280)


try:
    from astrbot.api.provider import ProviderRequest
    from astrbot.core.agent.message import Message, dump_messages_with_checkpoints
except ModuleNotFoundError:
    ProviderRequest = None


@unittest.skipUnless(ProviderRequest and PIL_AVAILABLE, 'Requires the AstrBot runtime')
class RequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.router = type('Router', (h.HistoryImagesMixin,), {})()
        self.router.config = {'platform_id': 'qq', 'history_images': {'enabled': True}}
        self.router._at_only_decision = lambda event: None
        provider = SimpleNamespace(provider_config={'modalities': ['text', 'image']})
        self.router.context = SimpleNamespace(get_config=lambda **kwargs: {'agent_runner': {'runner_type': 'local'}},
                                             get_using_provider_async=AsyncMock(return_value=provider))
        self.extra = {}
        self.event = SimpleNamespace(
            get_platform_id=lambda: 'qq', get_group_id=lambda: '1', get_sender_id=lambda: '10',
            get_self_id=lambda: '99', unified_msg_origin='qq:GroupMessage:1',
            get_extra=lambda key, default=None: self.extra.get(key, default),
            set_extra=lambda key, value: self.extra.update({key: value}),
            message_obj=SimpleNamespace(message_id='100', timestamp=10000,
                                        raw_message={'message': [], 'message_seq': 100}),
            bot=SimpleNamespace(call_action=AsyncMock(return_value={'messages': [picture(1, 9990), plain(100, 10000)]})),
        )
        from PIL import Image
        data = io.BytesIO(); Image.new('RGB', (100, 100), 'blue').save(data, 'PNG')
        self.loader = AsyncMock(return_value=data.getvalue())
        self.router._history_image_cache = h.ImageCache(loader=self.loader)

    async def asyncTearDown(self):
        await self.router._history_image_cache.close()

    async def test_same_request_contains_image_but_saved_history_does_not(self):
        request = ProviderRequest(prompt='左边一列是什么')
        await self.router._attach_history_images(self.event, request)
        assembled = await request.assemble_context()
        images = [part for part in assembled['content'] if part['type'] == 'image_url']
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]['_no_save'])
        self.assertTrue(images[0]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        message = Message.model_validate(assembled)
        saved = dump_messages_with_checkpoints([message])
        self.assertEqual(saved[0]['content'], [{'type': 'text', 'text': '左边一列是什么'}])
        self.event.bot.call_action.assert_awaited_once_with('get_group_msg_history', group_id=1, count=60, message_seq=100)
        self.assertEqual(self.extra['group_media_history_image_count'], 1)

    async def test_disabled_or_policy_blocked_request_does_no_io(self):
        self.router.config['history_images']['enabled'] = False
        await self.router._attach_history_images(self.event, ProviderRequest(prompt='hello'))
        self.router.config['history_images']['enabled'] = True
        self.extra['group_media_probability_blocked'] = True
        await self.router._attach_history_images(self.event, ProviderRequest(prompt='hello'))
        self.event.bot.call_action.assert_not_awaited()
        self.loader.assert_not_awaited()

    async def test_unsupported_provider_private_and_background_events_do_no_io(self):
        provider = SimpleNamespace(provider_config={'modalities': ['text']})
        self.router.context.get_using_provider_async.return_value = provider
        await self.router._attach_history_images(self.event, ProviderRequest(prompt='hello'))
        self.extra.clear(); self.event.get_group_id = lambda: ''
        await self.router._attach_history_images(self.event, ProviderRequest(prompt='hello'))
        self.event.bot.call_action.assert_not_awaited()

    async def test_failed_download_adds_no_unverified_image(self):
        self.router._history_image_cache.loader = AsyncMock(side_effect=ValueError('expired'))
        request = ProviderRequest(prompt='hello')
        await self.router._attach_history_images(self.event, request)
        self.assertEqual(request.extra_user_content_parts, [])
        self.assertNotIn('group_media_history_image_count', self.extra)

    async def test_event_deduplication_avoids_fetching_twice(self):
        request = ProviderRequest(prompt='hello')
        await self.router._attach_history_images(self.event, request)
        await self.router._attach_history_images(self.event, request)
        self.assertEqual(self.event.bot.call_action.await_count, 1)
        self.assertEqual(sum(p.type == 'image_url' for p in request.extra_user_content_parts), 1)


if __name__ == '__main__':
    unittest.main()
