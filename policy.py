"""Pure OneBot message classification; no network or model calls."""
import json
import re
from .heybox import extract_refs

BILI = re.compile(r"(?<![\w.])(?:https?://)?(?:www\.|m\.)?(?:b23\.tv/[A-Za-z0-9]+|bilibili\.com/video/(?:BV[A-Za-z0-9]{10}|av\d+))|(?<![A-Za-z0-9])BV[A-Za-z0-9]{10}(?![A-Za-z0-9])")

def sticker(data):
    return (str(data.get('sub_type', data.get('subType', ''))) == '1'
            or bool(data.get('emoji_id') or data.get('emoji_package_id'))
            or str(data.get('summary', '')).strip() in ('动画表情', '[动画表情]', '[表情]', '[商城表情]'))

def classify(segments):
    text, cards, images, faces, forwards = [], [], False, False, []
    for segment in segments:
        kind, data = segment.get('type'), segment.get('data') or {}
        if kind == 'text': text.append(str(data.get('text', '')))
        elif kind == 'image':
            if sticker(data): faces = True
            else: images = True
        elif kind in ('face', 'mface', 'marketface'): faces = True
        elif kind == 'forward' and data.get('id'): forwards.append(str(data['id']))
        elif kind == 'json':
            raw = data.get('data', {})
            try: raw = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError): raw = {}
            cards.append(json.dumps(raw, ensure_ascii=False).replace('\\/', '/'))
            if isinstance(raw, dict) and raw.get('app') == 'com.tencent.multimsg':
                detail = raw.get('meta', {}).get('detail', {})
                fid = detail.get('resid') or detail.get('uniseq')
                if fid: forwards.append(str(fid))
    match = BILI.search('\n'.join(text + cards))
    # An outer merged forward is treated as a conversation, not one nested link.
    if forwards: return 'forward', forwards
    heybox = extract_refs(segments)
    if heybox: return 'heybox', heybox[0]
    if match: return 'bilibili', match.group(0)
    if images: return 'image', None
    if ''.join(text).strip(): return 'chat', None
    if faces: return 'sticker', None
    return 'other', None
