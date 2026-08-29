# py/llm.py — OpenAI 兼容 API 客户端（Python urllib，出网正常）
import json
import urllib.request
import urllib.error

DEFAULT_BASE = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-chat'

def to_chat_url(base):
    b = (base or DEFAULT_BASE).strip().rstrip('/')
    if not b.endswith('/chat/completions'):
        if not b.endswith('/v1'):
            b += '/v1'
        b += '/chat/completions'
    return b

def chat(base, key, model, messages, temperature=0.7, on_delta=None):
    if not key:
        raise ValueError('未配置 API Key，请在「设置」中填写')
    url = to_chat_url(base)
    body = json.dumps({
        'model': model or DEFAULT_MODEL,
        'messages': messages,
        'temperature': temperature,
        'stream': True,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + key.strip(),
    })
    try:
        resp = urllib.request.urlopen(req, timeout=240)
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'ignore')[:300]
        raise ValueError('API 错误 %s: %s' % (e.code, detail))
    except urllib.error.URLError as e:
        raise ValueError('网络错误: %s' % e.reason)

    full = ''
    for raw in resp:
        line = raw.decode('utf-8').strip()
        if not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if payload == '[DONE]':
            continue
        try:
            j = json.loads(payload)
            delta = ''
            choices = j.get('choices')
            if choices:
                delta = ((choices[0].get('delta') or {}) or {}).get('content') or ''
            if delta:
                full += delta
                if on_delta:
                    on_delta(delta)
        except Exception:
            pass
    return full
