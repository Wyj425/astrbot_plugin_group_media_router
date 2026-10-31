"""Defaults and partial per-group overrides. Probabilities use percent in the UI."""
import copy
import hashlib
import json
import math
import re

FIELDS = {'chat': 'chat_percent', 'image': 'image_percent',
          'bilibili': 'bilibili_percent', 'forward': 'forward_percent', 'heybox': 'heybox_percent'}
BASE_DEFAULTS = {'chat_percent': 20, 'image_percent': 100,
                 'bilibili_percent': 100, 'forward_percent': 100, 'heybox_percent': 100, 'at_only_users': []}


def _percent(value, fallback):
    if isinstance(value, bool): return fallback
    try: value = float(value)
    except (TypeError, ValueError): return fallback
    return value if math.isfinite(value) and 0 <= value <= 100 else fallback


def _ids(values):
    if not isinstance(values, list): return []
    return sorted({str(int(str(v).strip())) for v in values if not isinstance(v, bool)
                   and re.fullmatch(r'[0-9]{1,20}', str(v).strip()) and int(str(v).strip()) > 0})


def migrate(config, names=None):
    """Preserve existing behavior, including the old group:QQ mention-only list."""
    result = copy.deepcopy(dict(config))
    if isinstance(result.get('default_rules'), dict):
        result['default_rules'].setdefault('heybox_percent', 100)
        result['rules_version'] = 2
        return result
    defaults = copy.deepcopy(BASE_DEFAULTS)
    defaults['chat_percent'] = _percent(_percent(result.get('chat_probability', .2), .2) * 100, 20)
    groups = {}
    for old in result.get('at_only_users', []):
        if not isinstance(old, str): continue
        parts = old.split(':')
        if len(parts) != 2 or not all(x.isdigit() and int(x) > 0 for x in parts): continue
        gid, uid = map(lambda x: str(int(x)), parts)
        row = groups.setdefault(gid, {'__template_key':'group','group_id':gid,
            'group_name':(names or {}).get(gid,''),'at_only_mode':'单独设置','at_only_users':[]})
        row['at_only_users'] = _ids(row['at_only_users'] + [uid])
    result.update(rules_version=2, default_rules=defaults, group_rules=list(groups.values()))
    result.pop('chat_probability', None)
    result.pop('at_only_users', None)
    return result


def resolve(config, group_id):
    current = config if isinstance(config.get('default_rules'), dict) else migrate(config)
    raw = current.get('default_rules', {})
    values = {k:_percent(raw.get(k), v) for k,v in BASE_DEFAULTS.items() if k != 'at_only_users'}
    values['at_only_users'] = _ids(raw.get('at_only_users', []))
    source, inherited = 'default', list(BASE_DEFAULTS)
    for row in current.get('group_rules', []):
        if not isinstance(row, dict) or str(row.get('group_id')) != str(group_id): continue
        source = 'group'
        for key in FIELDS.values():
            override = _percent(row.get(key), None)
            if override is not None:
                values[key] = override
                inherited.remove(key)
        if row.get('at_only_mode', '继承默认') == '单独设置':
            values['at_only_users'] = _ids(row.get('at_only_users', []))
            inherited.remove('at_only_users')
        break
    return {**values, 'source':source, 'inherited':inherited}


def selected(rule, kind, explicit, draw):
    if explicit: return True
    return kind in FIELDS and draw < rule[FIELDS[kind]] / 100


def revision(config):
    data = {k:config.get(k) for k in ['default_rules','group_rules','chat_probability','at_only_users']}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate(defaults, groups):
    """Validate an entire edit before mutating the live configuration."""
    if not isinstance(defaults, dict) or not isinstance(groups, list):
        raise ValueError('默认规则必须为对象，群规则必须为列表')
    if len(groups) > 1000: raise ValueError('群规则最多支持 1000 项')

    def ids(value):
        if not isinstance(value, list) or len(value) > 1000: raise ValueError('仅@回复名单应为 QQ 号列表，最多 1000 人')
        clean = _ids(value)
        if any(isinstance(v,bool) or not re.fullmatch(r'[0-9]{1,20}',str(v).strip()) or int(str(v).strip()) <= 0 for v in value):
            raise ValueError('名单只填写有效 QQ 号，不填昵称或群号:QQ号')
        return clean

    def percent(value, inherit=False):
        if inherit and value == -1 and not isinstance(value,bool): return -1
        if not isinstance(value,(int,float)) or isinstance(value,bool) or _percent(value,None) is None:
            raise ValueError('回复概率必须为 0–100；群规则可填 -1 沿用默认')
        return value

    out_defaults = {key:percent(defaults.get(key, val)) for key,val in BASE_DEFAULTS.items() if key != 'at_only_users'}
    out_defaults['at_only_users'] = ids(defaults.get('at_only_users', []))
    seen, out_groups = set(), []
    for row in groups:
        if not isinstance(row,dict): raise ValueError('每条群规则必须为对象')
        gid = str(row.get('group_id','')).strip()
        if not re.fullmatch(r'[0-9]{1,20}',gid) or int(gid) <= 0: raise ValueError('请填写有效的纯数字群号')
        gid = str(int(gid))
        if gid in seen: raise ValueError('同一个群只能配置一条规则：'+gid)
        seen.add(gid)
        mode = row.get('at_only_mode','继承默认')
        if mode not in ['继承默认','单独设置']: raise ValueError('仅@回复名单模式无效')
        clean = {'__template_key':'group','group_id':gid,'group_name':str(row.get('group_name',''))[:120],
                 'at_only_mode':mode,'at_only_users':ids(row.get('at_only_users',[]))}
        clean.update({key:percent(row.get(key,-1),True) for key in FIELDS.values()})
        out_groups.append(clean)
    return out_defaults, out_groups
