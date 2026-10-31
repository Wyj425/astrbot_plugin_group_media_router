"""Pure card destination parsing; content reading lives in the platform plugin."""
import html,json,re
from urllib.parse import urlsplit,parse_qs
HOSTS = {'api.xiaoheihe.cn', 'www.xiaoheihe.cn', 'xiaoheihe.cn', 'www.xiaoheihe.com', 'xiaoheihe.com'}
URLS = re.compile(r'https?://[^\s<>"\u201c\u201d]+', re.I)
POST_ID = re.compile(r'^[A-Za-z0-9]{1,40}$')

def post_ref(url):
    """Only trusted post URLs are converted to a fixed API call; never fetch input URLs."""
    try:
        url = html.unescape(str(url)).strip().rstrip('。，、)）]')
        p = urlsplit(url)
        if p.scheme not in ('http','https') or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,80,443): return None
        query = parse_qs(p.query)
        ident = query.get('link_id', [''])[0]
        if not ident:
            match = re.search(r'/(?:app/bbs/link|bbs/link|posts?)/([A-Za-z0-9]{1,40})(?:/|$)', p.path)
            ident = match[1] if match else ''
        if not POST_ID.fullmatch(ident): return None
        return {'id': ident, 'url': 'https://api.xiaoheihe.cn/v3/bbs/app/api/web/share?link_id=' + ident}
    except (TypeError, ValueError): return None

def extract_refs(segments):
    """Do not mistake a preview image/tag for a destination or mine quoted histories."""
    refs=[]
    def walk(value, depth=0):
        if depth > 8: return
        if isinstance(value, dict):
            for k,v in value.items():
                if k.lower() in ('jumpurl','url','qqdocurl','targeturl','link','share_url') and isinstance(v,str):
                    ref=post_ref(v)
                    if ref: refs.append(ref)
                elif isinstance(v,(dict,list)):walk(v,depth+1)
        elif isinstance(value,list):
            for v in value[:40]:walk(v,depth+1)
    for s in segments if isinstance(segments,list) else []:
        if not isinstance(s,dict):continue
        data=s.get('data') or {}
        if not isinstance(data,dict):continue
        if s.get('type')=='text':
            for url in URLS.findall(str(data.get('text',''))):
                ref=post_ref(url)
                if ref:refs.append(ref)
        elif s.get('type')=='json':
            raw=data.get('data',{})
            try:raw=json.loads(raw) if isinstance(raw,str) else raw
            except (ValueError,TypeError):continue
            walk(raw)
    unique={r['id']:r for r in refs}
    return list(unique.values())[:2]

