"""Keep companion plugin sends in the active reply's QQ message budget."""


class ContextReplySender:
    def __init__(self, router, current_event):
        self.router = router
        self.context = router.context
        self.current_event = current_event
        self.original = self.context.send_message
        self.handler = self.send
        self.active = True

    def install(self):
        self.context.send_message = self.handler

    def remove(self):
        self.active = False
        if self.context.send_message is self.handler:
            self.context.send_message = self.original

    async def send(self, session, message_chain):
        event = self.current_event()
        rule = self.router._reply_limit(event) if event is not None else None
        if (not self.active or event is None or not getattr(event, '_execution_active', False)
                or str(session) != event.unified_msg_origin or rule is None or rule[1] <= 0):
            return await self.original(session, message_chain)
        # The framework binds current_message_event for the whole event pipeline,
        # including after_message_sent. Extra stickers sent with Context therefore
        # use the same event-local adapter proxy as text and voice segments.
        self.router._install_send_budget(event)
        before = event.get_extra('group_media_reply_sent_messages', 0)
        await event.send(message_chain)
        accepted = event.get_extra('group_media_reply_sent_messages', 0) > before
        if not accepted or event.get_extra('group_media_reply_limit_blocked', False):
            return False
        # Preserve Context.send_message's platform-history behavior, without
        # inventing an image record when the budget prevented its delivery.
        settings = self.context.get_config(umo=str(session)).get('provider_ltm_settings', {})
        if settings.get('group_message_history_enable', False):
            try:
                await self.context.message_history_manager.insert_message_chain(
                    platform_id=event.get_platform_id(), user_id=str(session), message_chain=message_chain,
                    role='bot', sender_id='bot', sender_name='bot',
                    max_messages=max(1, int(settings.get('group_message_history_max_cnt', 700))))
            except Exception:
                from astrbot.api import logger
                logger.exception('[group_media_router] companion reply history sync failed')
        return True
