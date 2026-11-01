import copy
import unittest
from types import SimpleNamespace
from _load import load

policy = load('reply_limit')
rules = load('rules')


class Clock:
    value = 1000
    def __call__(self): return self.value


class Event:
    def __init__(self, group='1', segments=None, platform='qq', route=True):
        self.extra = {'group_media_route': ('chat', None)} if route else {}
        self.group = group
        self.platform = platform
        self.unified_msg_origin = f'{platform}:GroupMessage:{group}'
        self.message_obj = SimpleNamespace(raw_message={'message': segments or [
            {'type': 'text', 'data': {'text': 'hello'}}]})
        self.is_at_or_wake_command = False
        self._has_send_oper = False
    def get_extra(self, key, default=None): return self.extra.get(key, default)
    def set_extra(self, key, value): self.extra[key] = value
    def get_group_id(self): return self.group
    def get_platform_id(self): return self.platform
    def get_self_id(self): return '99'


class Subject(policy.ReplyLimitMixin):
    def __init__(self, limit=1):
        self.clock = Clock()
        self._reply_budget = policy.ReplyWindow(self.clock)
        self.config = {'platform_id': 'qq', 'default_rules': {
            **copy.deepcopy(rules.BASE_DEFAULTS), 'reply_limit_per_minute': limit}, 'group_rules': []}


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.window = policy.ReplyWindow(self.clock)

    def test_receiving_or_checking_many_messages_does_not_spend_quota(self):
        for _ in range(100): self.assertTrue(self.window.available('g', 1))

    def test_success_counts_until_exactly_sixty_seconds_after_delivery(self):
        self.assertTrue(self.window.reserve('g', 'a', 1))
        self.clock.value += 30
        self.assertTrue(self.window.commit('g', 'a'))
        self.clock.value += 59.999
        self.assertFalse(self.window.available('g', 1))
        self.clock.value += .001
        self.assertTrue(self.window.available('g', 1))

    def test_parallel_ready_responses_cannot_overbook(self):
        self.assertTrue(self.window.reserve('g', 'a', 1))
        self.assertFalse(self.window.reserve('g', 'b', 1))
        self.assertTrue(self.window.reserve('g', 'a', 1))

    def test_other_groups_and_platforms_are_independent(self):
        self.window.reserve(('qq', '1'), 'a', 1)
        self.assertTrue(self.window.available(('qq', '2'), 1))
        self.assertTrue(self.window.available(('other', '1'), 1))

    def test_failed_send_releases_reservation_without_counting(self):
        self.window.reserve('g', 'a', 1)
        self.window.release('g', 'a')
        self.assertTrue(self.window.available('g', 1))
        self.assertFalse(self.window.commit('g', 'a'))

    def test_double_after_send_cannot_count_twice(self):
        self.window.reserve('g', 'a', 2)
        self.assertTrue(self.window.commit('g', 'a'))
        self.assertFalse(self.window.commit('g', 'a'))
        self.assertTrue(self.window.available('g', 2))

    def test_abandoned_reservations_expire(self):
        self.window.reserve('g', 'a', 1)
        self.clock.value += 300
        self.assertTrue(self.window.reserve('g', 'b', 1))

    def test_lower_limit_applies_to_pending_responses(self):
        self.window.reserve('g', 'a', 2)
        self.window.reserve('g', 'b', 2)
        self.assertTrue(self.window.reserve('g', 'a', 1))
        self.assertFalse(self.window.reserve('g', 'b', 1))

    def test_zero_is_unlimited(self):
        for i in range(100): self.assertTrue(self.window.reserve('g', str(i), 0))
        self.assertEqual(self.window.groups, {})


class EventTests(unittest.TestCase):
    def test_at_reply_neither_uses_nor_needs_quota(self):
        o = Subject()
        regular = Event()
        self.assertTrue(o._reserve_reply(regular))
        regular._has_send_oper = True
        o._finish_reply(regular)
        for _ in range(10):
            at = Event(segments=[{'type': 'at', 'data': {'qq': '99'}}])
            self.assertTrue(o._reserve_reply(at))
            at._has_send_oper = True
            o._finish_reply(at)
        self.assertFalse(o._reply_limit_available(Event()))

    def test_at_all_literal_mention_quote_and_wake_flag_are_not_exempt(self):
        for segments in [[{'type': 'at', 'data': {'qq': 'all'}}],
                         [{'type': 'text', 'data': {'text': '@大肥鱼'}}],
                         [{'type': 'reply', 'data': {'id': '123'}}],
                         [{'type': 'at', 'data': {'qq': 'another'}}]]:
            o = Subject()
            first = Event()
            o._reserve_reply(first)
            e = Event(segments=segments)
            e.is_at_or_wake_command = True
            self.assertFalse(o._reserve_reply(e))

    def test_failed_delivery_does_not_count(self):
        o = Subject()
        e = Event()
        o._reserve_reply(e)
        o._finish_reply(e)
        self.assertTrue(o._reply_limit_available(Event()))

    def test_non_replies_private_other_platform_and_scheduled_events_are_excluded(self):
        o = Subject()
        events = [Event(route=False), Event(group=''), Event(platform='another')]
        scheduled = Event()
        scheduled._proactive_plugin = object()
        events.append(scheduled)
        for event in events:
            self.assertIsNone(o._reply_limit(event))
            self.assertTrue(o._reserve_reply(event))
        self.assertTrue(o._reply_limit_available(Event()))

    def test_other_group_and_group_override(self):
        o = Subject()
        o.config['group_rules'] = [{'group_id': '2', 'reply_limit_per_minute': 0}]
        a = Event()
        o._reserve_reply(a)
        a._has_send_oper = True
        o._finish_reply(a)
        self.assertTrue(o._reply_limit_available(Event(group='2')))
        self.assertTrue(o._reply_limit_available(Event(group='3')))

    def test_empty_and_header_only_results_are_not_replies(self):
        o = Subject()
        self.assertFalse(o._has_reply_content(None))
        self.assertFalse(o._has_reply_content(SimpleNamespace(chain=[])))
        self.assertFalse(o._has_reply_content(SimpleNamespace(chain=[SimpleNamespace(text='  ')])))
        At = type('At', (), {})
        Reply = type('Reply', (), {})
        self.assertFalse(o._has_reply_content(SimpleNamespace(chain=[At(), Reply()])))
        self.assertTrue(o._has_reply_content(SimpleNamespace(chain=[SimpleNamespace(text='hello')])))

    def test_event_cancellation_frees_unsent_reservation(self):
        import gc
        o = Subject()
        e = Event()
        o._reserve_reply(e)
        del e
        gc.collect()
        self.assertTrue(o._reply_limit_available(Event()))


class LimitRuleTests(unittest.TestCase):
    def test_existing_settings_migrate_without_enabling_limit(self):
        old = {'default_rules': {'chat_percent': 37}, 'group_rules': []}
        migrated = rules.migrate(old)
        self.assertEqual(migrated['default_rules']['reply_limit_per_minute'], 0)
        self.assertNotIn('reply_limit_per_minute', old['default_rules'])
        self.assertEqual(rules.resolve(migrated, '1')['chat_percent'], 37)

    def test_group_limit_inherits_changes_and_zero_disables(self):
        config = {'default_rules': {**rules.BASE_DEFAULTS, 'reply_limit_per_minute': 5},
            'group_rules': [{'group_id': '1', 'reply_limit_per_minute': -1},
                            {'group_id': '2', 'reply_limit_per_minute': 0},
                            {'group_id': '3', 'reply_limit_per_minute': 2}]}
        self.assertEqual([rules.resolve(config, g)['reply_limit_per_minute'] for g in ['1','2','3','4']], [5,0,2,5])
        config['default_rules']['reply_limit_per_minute'] = 7
        self.assertEqual(rules.resolve(config, '1')['reply_limit_per_minute'], 7)

    def test_integer_bounds_and_inheritance_are_validated(self):
        for value in [-1, 601, True, 1.5, '5', float('nan')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                rules.validate({**rules.BASE_DEFAULTS, 'reply_limit_per_minute': value}, [])
        defaults, groups = rules.validate({**rules.BASE_DEFAULTS, 'reply_limit_per_minute': 600},
            [{'group_id': '1', 'reply_limit_per_minute': -1}, {'group_id': '2', 'reply_limit_per_minute': 0}])
        self.assertEqual(defaults['reply_limit_per_minute'], 600)
        self.assertEqual([g['reply_limit_per_minute'] for g in groups], [-1, 0])

    def test_invalid_official_config_value_falls_back(self):
        c = {'default_rules': {'reply_limit_per_minute': True}, 'group_rules': []}
        self.assertEqual(rules.resolve(c, '1')['reply_limit_per_minute'], 0)


if __name__ == '__main__': unittest.main()
