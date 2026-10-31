"""Authenticated AstrBot plugin-page API. Does not open another port."""
import asyncio
import copy
import time
from quart import request
from .rules import migrate, resolve, revision, validate


class RulesPageMixin:
    async def initialize(self):
        self._rule_lock = asyncio.Lock()
        self._group_cache = []
        self._group_cache_at = 0
        self.context.register_web_api('/group_media_router/rules', self.rules_get, ['GET'], '读取默认及各群回复规则')
        self.context.register_web_api('/group_media_router/rules', self.rules_save, ['POST'], '保存默认及各群回复规则')

    async def _rule_groups(self):
        error = ''
        if time.monotonic() - self._group_cache_at > 60:
            try:
                platform = self.context.get_platform_inst(self.config.get('platform_id',''))
                if not platform: raise RuntimeError('QQ 平台尚未连接')
                rows = await asyncio.wait_for(platform.get_client().call_action('get_group_list'),10)
                if isinstance(rows,dict): rows = rows.get('data',[])
                if not isinstance(rows,list): raise ValueError('群列表格式无效')
                self._group_cache = [{'group_id':str(x['group_id']), 'group_name':str(x.get('group_name',''))}
                    for x in rows if isinstance(x,dict) and str(x.get('group_id','')).isdigit()]
                self._group_cache_at = time.monotonic()
            except Exception:
                error = '暂时无法读取 QQ 群列表，仍可管理已保存的规则。'
        groups = {x['group_id']:dict(x) for x in self._group_cache}
        for row in self.config.get('group_rules',[]):
            if isinstance(row,dict) and row.get('group_id'):
                groups.setdefault(str(row['group_id']),{'group_id':str(row['group_id']),'group_name':row.get('group_name','')})
        return sorted(groups.values(),key=lambda x:(x['group_name'],x['group_id'])), error

    async def _rule_payload(self):
        snapshot = copy.deepcopy(dict(self.config))
        current = migrate(snapshot)
        version = revision(snapshot)
        groups, warning = await self._rule_groups()
        return {'default_rules':copy.deepcopy(current['default_rules']),
                'group_rules':copy.deepcopy(current.get('group_rules',[])),
                'groups':[{**g,'effective':resolve(current,g['group_id'])} for g in groups],
                'revision':version,'warning':warning}

    async def rules_get(self):
        return {'status':'ok','data':await self._rule_payload()}

    async def rules_save(self):
        payload = await request.get_json(silent=True) or {}
        if not isinstance(payload,dict): return {'status':'error','message':'请求格式错误'}
        try: defaults, groups = validate(payload.get('default_rules'),payload.get('group_rules'))
        except ValueError as exc: return {'status':'error','message':str(exc)}
        async with self._rule_lock:
            if payload.get('revision') != revision(self.config):
                return {'status':'error','message':'规则已在其他页面修改，请重新读取后再保存。'}
            before = dict(self.config)
            self.config.update(rules_version=2,default_rules=defaults,group_rules=groups)
            self.config.pop('chat_probability',None)
            self.config.pop('at_only_users',None)
            try: self.config.save_config()
            except Exception:
                self.config.clear();self.config.update(before)
                return {'status':'error','message':'保存失败，已保留原有规则。'}
        return {'status':'ok','data':await self._rule_payload()}
