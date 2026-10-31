"""Expire only unsolicited text chatter; preserve questions and requested media."""
import math
import re


def is_question(text):
    return bool(re.search(r'[?？]|为什么|怎么|如何|咋|啥|能不能|可不可以|有没有|是不是|能否|是否|什么|多少|几[个点块天次米]|哪[里个儿]|谁|(?:吗|么|嘛)[呀啊呢吧~～。！!\s]*$|\b(?:why|how|what|who|where|when)\b',str(text or ''),re.I))


def stale_chat(kind,explicit,text,received,now,limit):
    if kind!='chat' or explicit or is_question(text) or str(text or '').lstrip().startswith('/'):
        return False
    try:
        if float(received)<=0:return False
        age=float(now)-float(received)
    except (ValueError,TypeError):return False
    return math.isfinite(age) and age>max(5,float(limit))
