"""Per-group rolling reply budget; incoming messages never spend this budget."""
from collections import deque
import time
import uuid
import weakref

from .mention_policy import mentions_bot
from .rules import resolve


class ReplyWindow:
    def __init__(self, clock=time.monotonic, window=60, reservation_ttl=300):
        self.clock = clock
        self.window = window
        self.reservation_ttl = reservation_ttl
        self.groups = {}

    def _bucket(self, key):
        now = self.clock()
        for group, bucket in list(self.groups.items()):
            while bucket['sent'] and bucket['sent'][0] <= now - self.window:
                bucket['sent'].popleft()
            for token, started in list(bucket['pending'].items()):
                if started <= now - self.reservation_ttl:
                    del bucket['pending'][token]
            if not bucket['sent'] and not bucket['pending']:
                del self.groups[group]
        return self.groups.setdefault(key, {'sent': deque(), 'pending': {}})

    def available(self, key, limit):
        if limit <= 0:
            return True
        bucket = self._bucket(key)
        return len(bucket['sent']) + len(bucket['pending']) < limit

    def reserve(self, key, token, limit):
        if limit <= 0:
            self.release(key, token)
            return True
        bucket = self._bucket(key)
        pending = bucket['pending']
        if token in pending:
            # A lower limit saved while responses were being generated applies
            # before sending, while retaining the oldest allowed reservations.
            return len(bucket['sent']) + list(pending).index(token) < limit
        if len(bucket['sent']) + len(pending) >= limit:
            return False
        pending[token] = self.clock()
        return True

    def release(self, key, token):
        bucket = self.groups.get(key)
        if bucket:
            bucket['pending'].pop(token, None)

    def commit(self, key, token):
        bucket = self._bucket(key)
        if token not in bucket['pending']:
            return False
        del bucket['pending'][token]
        bucket['sent'].append(self.clock())
        return True


class ReplyLimitMixin:
    def _reply_window(self):
        if not hasattr(self, '_reply_budget'):
            self._reply_budget = ReplyWindow()
        return self._reply_budget

    def _reply_limit(self, event):
        if (event.get_platform_id() != self.config.get('platform_id', '')
                or not event.get_group_id()
                or getattr(event, '_proactive_plugin', None) is not None
                or not event.get_extra('group_media_route')):
            return None
        allowed = self.config.get('allowed_groups', [])
        if allowed and str(event.get_group_id()) not in allowed and event.unified_msg_origin not in allowed:
            return None
        raw = event.message_obj.raw_message
        segments = raw.get('message', []) if hasattr(raw, 'get') else []
        # Only a real mention of this bot is exempt, not @all, literal text,
        # quoting the bot or a wake flag set by another plugin.
        if mentions_bot(segments, event.get_self_id()):
            return None
        return ((event.get_platform_id(), str(event.get_group_id())),
                resolve(self.config, event.get_group_id())['reply_limit_per_minute'])

    def _reply_limit_available(self, event):
        rule = self._reply_limit(event)
        return rule is None or self._reply_window().available(*rule)

    def _reserve_reply(self, event):
        rule = self._reply_limit(event)
        if rule is None or rule[1] <= 0:
            self._release_reply(event)
            return True
        reservation = event.get_extra('group_media_reply_reservation')
        if reservation is None:
            reservation = (rule[0], uuid.uuid4().hex)
        if not self._reply_window().reserve(rule[0], reservation[1], rule[1]):
            self._release_reply(event)
            return False
        event.set_extra('group_media_reply_reservation', reservation)
        if event.get_extra('group_media_reply_finalizer') != reservation[1]:
            try:
                weakref.finalize(event, self._reply_window().release, *reservation)
                event.set_extra('group_media_reply_finalizer', reservation[1])
            except TypeError:
                pass
        return True

    def _release_reply(self, event):
        reservation = event.get_extra('group_media_reply_reservation')
        if reservation:
            self._reply_window().release(*reservation)
            event.set_extra('group_media_reply_reservation', None)

    def _finish_reply(self, event):
        reservation = event.get_extra('group_media_reply_reservation')
        if not reservation:
            return
        if getattr(event, '_has_send_oper', False):
            self._reply_window().commit(*reservation)
        else:
            self._reply_window().release(*reservation)
        event.set_extra('group_media_reply_reservation', None)

    @staticmethod
    def _has_reply_content(result):
        if result is None:
            return False
        for component in getattr(result, 'chain', []) or []:
            if component.__class__.__name__ in ('At', 'AtAll', 'Reply'):
                continue
            text = getattr(component, 'text', None)
            if text is None or str(text).strip():
                return True
        return False
