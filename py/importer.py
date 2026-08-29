# py/importer.py — 各种聊天导出格式归一化（移植自 Node lib/importer.js + WeFlow 修复）
# 统一结构: {contact, selfName, source, messages:[{sender:'me'|'them', content, ts(秒), type}]}

import json
import re

TYPE_MAP = {
    '文本消息': 'text', '图片消息': 'image', '语音消息': 'voice', '视频消息': 'video',
    '动画表情': 'emoji', '表情': 'emoji', '通话消息': 'system', '链接消息': 'link',
    '引用消息': 'text', '转账消息': 'system', '系统消息': 'system', '红包': 'system',
    '文件消息': 'file', '撤回消息': 'revoke',
}

def detect_format(payload, file_name=''):
    if isinstance(payload, str):
        trimmed = payload.strip()
        obj = None
        if trimmed.startswith('{') or trimmed.startswith('['):
            try:
                obj = json.loads(trimmed)
            except Exception:
                return 'markdown'
        else:
            return 'markdown'
    else:
        obj = payload

    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            f = obj[0]
            if 'isSend' in f or 'senderUsername' in f:
                if 'createTime' in f:
                    return 'weflow'
            if 'sender' in f or 'fromUser' in f or 'message' in f or 'msg' in f:
                return 'weflow'
            if 'local_id' in f or ('sender' in f and 'timestamp' in f and 'content' in f):
                return 'normalized'
        return 'markdown'

    if isinstance(obj, dict):
        if isinstance(obj.get('messages'), list):
            first = obj['messages'][0] if obj['messages'] else {}
            if obj.get('metadata') and obj.get('chatInfo'):
                return 'qce'
            if obj.get('weflow') or (obj.get('session') and isinstance(first, dict) and 'createTime' in first):
                return 'weflow'
            if obj.get('source') or obj.get('bundle_dir'):
                return 'normalized'
            if isinstance(first, dict) and 'isSend' in first:
                return 'weflow'
            return 'generic'
        if obj.get('contact_username') or obj.get('own_wxid'):
            return 'normalized'
    return 'generic'

def _html_entities(s):
    return (s.replace('&#x20;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>'))

def from_qce(payload):
    if isinstance(payload, str):
        obj = json.loads(payload)
    else:
        obj = payload
    chat_info = obj.get('chatInfo') or {}
    self_uin = str(chat_info.get('selfUin') or chat_info.get('selfUid') or '')
    messages = []
    for m in (obj.get('messages') or []):
        sender = (m.get('sender') or {})
        sender_uin = str(sender.get('uin') or sender.get('uid') or '')
        is_me = (sender_uin == self_uin)
        content = ''
        c = m.get('content')
        if isinstance(c, dict):
            content = c.get('text') or ''
            if not content and c.get('elements'):
                parts = []
                for e in c['elements']:
                    d = e.get('data') or {}
                    v = d.get('text') or d.get('value') or ''
                    if v:
                        parts.append(v)
                content = ' '.join(parts)
        elif isinstance(c, str):
            content = c
        ts = 0
        if m.get('timestamp'):
            ts = int(m['timestamp']) // 1000
        elif m.get('time'):
            try:
                import datetime
                ts = int(datetime.datetime.strptime(str(m['time'])[:19], '%Y-%m-%d %H:%M:%S').timestamp())
            except Exception:
                ts = 0
        mtype = (m.get('type') or 'text').lower()
        if m.get('recalled'):
            mtype = 'revoke'
        if mtype == 'audio':
            mtype = 'voice'
        if mtype in ('face', 'sticker'):
            mtype = 'emoji'
        if mtype == 'system' or m.get('system'):
            mtype = 'system'
        if ts > 0:
            messages.append({'sender': 'me' if is_me else 'them', 'content': content or ('[%s]' % mtype), 'ts': ts, 'type': mtype})
    return {
        'contact': chat_info.get('name') or chat_info.get('peerName') or '未知联系人',
        'selfName': chat_info.get('selfName') or '',
        'source': 'QCE导出',
        'messages': messages,
    }

def from_normalized(payload):
    obj = json.loads(payload) if isinstance(payload, str) else payload
    lst = obj if isinstance(obj, list) else (obj.get('messages') or [])
    messages = []
    for m in lst:
        sender = m.get('sender')
        if sender in ('me', 'self', 0, '0'):
            sender = 'me'
        else:
            sender = 'them'
        content = m.get('content')
        if isinstance(content, dict):
            content = content.get('text') or json.dumps(content, ensure_ascii=False)
        ts = int(m.get('timestamp') or 0)
        if ts > 0:
            messages.append({'sender': sender, 'content': str(content or '[消息]'), 'ts': ts, 'type': m.get('type') or 'text'})
    return {
        'contact': obj.get('contact_display') or obj.get('contact_username') or '未知联系人',
        'selfName': '我',
        'source': '归一化JSON',
        'messages': messages,
    }

def from_weflow(payload):
    obj = json.loads(payload) if isinstance(payload, str) else payload
    lst = obj if isinstance(obj, list) else (obj.get('messages') or [])
    session = (obj.get('session') or {}) if isinstance(obj, dict) else {}
    my_wxid = session.get('wxid') or ''
    contact = session.get('nickname') or session.get('displayName') or session.get('remark') or '联系人'
    self_name = '我'
    for m in lst:
        if m.get('isSend') in (1, True, '1') and m.get('senderDisplayName'):
            self_name = m['senderDisplayName']
            break
    messages = []
    for m in lst:
        is_send = m.get('isSend') in (1, True, '1')
        sender = 'me' if (my_wxid and m.get('senderUsername') == my_wxid) else ('me' if is_send else 'them')
        content = m.get('content') or ''
        if isinstance(content, dict):
            content = content.get('text') or content.get('content') or json.dumps(content, ensure_ascii=False)
        content = _html_entities(str(content)).strip()
        ts = m.get('createTime') or 0
        if isinstance(ts, str):
            try:
                import datetime
                ts = int(datetime.datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S').timestamp())
            except Exception:
                ts = 0
        else:
            ts = int(ts or 0)
        mtype = TYPE_MAP.get(m.get('type') or '', 'text')
        if mtype == 'system' and re.search(r'撤回|recalled|revoke', m.get('type') or '', re.I):
            mtype = 'revoke'
        if ts > 0:
            messages.append({'sender': sender, 'content': content or ('[' + (m.get('type') or '消息') + ']'), 'ts': ts, 'type': mtype})
    return {'contact': contact or '联系人', 'selfName': self_name, 'source': 'WeFlow导出', 'messages': messages}

def from_markdown(payload):
    lines = str(payload).splitlines()
    messages = []
    for line in lines:
        m = re.match(r'^\s*[\[(](\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{0,2}:?\d{0,2}(?::\d{0,2})?)[\])]\s*(.+?)\s*[:：]\s*(.*)$', line)
        if not m:
            continue
        ts = 0
        try:
            import datetime
            ts = int(datetime.datetime.strptime(m.group(1).replace('/', '-').strip(), '%Y-%m-%d %H:%M').timestamp())
        except Exception:
            try:
                import datetime
                ts = int(datetime.datetime.strptime(m.group(1).replace('/', '-').strip(), '%Y-%m-%d').timestamp())
            except Exception:
                ts = 0
        name = m.group(2).strip()
        content = m.group(3).strip()
        if ts > 0 and content:
            sender = 'me' if re.search(r'(我|me|self)', name, re.I) else 'them'
            messages.append({'sender': sender, 'content': content, 'ts': ts, 'type': 'text'})
    return {'contact': '联系人', 'selfName': '我', 'source': '时间戳文本', 'messages': messages}

def from_generic(payload):
    obj = json.loads(payload) if isinstance(payload, str) else payload
    lst = obj if isinstance(obj, list) else (obj.get('messages') or obj.get('data') or [])
    messages = []
    for i, m in enumerate(lst):
        sender = 'me' if m.get('sender') in ('me', 'self', 0, '0') else 'them'
        content = m.get('content') or m.get('text') or m.get('msg') or ''
        if isinstance(content, dict):
            content = content.get('text') or json.dumps(content, ensure_ascii=False)
        ts = m.get('timestamp') or m.get('ts') or m.get('time') or 0
        if isinstance(ts, str):
            try:
                import datetime
                ts = int(datetime.datetime.strptime(str(ts)[:19], '%Y-%m-%d %H:%M:%S').timestamp())
            except Exception:
                ts = 0
        if isinstance(ts, int) and ts > 1e12:
            ts = ts // 1000
        ts = int(ts or 0)
        if ts > 0:
            messages.append({'sender': sender, 'content': str(content or ('[消息%d]' % i)), 'ts': ts, 'type': m.get('type') or 'text'})
    return {'contact': obj.get('contact') or obj.get('name') or '联系人', 'selfName': '我', 'source': '通用JSON', 'messages': messages}

def normalize(payload, fmt, file_name=''):
    if fmt == 'qce':
        return from_qce(payload)
    if fmt == 'normalized':
        return from_normalized(payload)
    if fmt == 'weflow':
        return from_weflow(payload)
    if fmt == 'markdown':
        return from_markdown(payload)
    if fmt == 'generic':
        return from_generic(payload)
    raise ValueError('无法识别的格式: ' + str(fmt))

# 整合多个平台记录（按时间合并 + 去重 + 平台来源拼接）
def merge_records(records):
    valid = [r for r in (records or []) if r and isinstance(r.get('messages'), list) and r['messages']]
    if not valid:
        return {'contact': '联系人', 'selfName': '我', 'source': '多平台整合', 'messages': []}
    seen = set()
    messages = []
    for rec in valid:
        for m in (rec.get('messages') or []):
            if not m or not m.get('ts'):
                continue
            key = '%s|%s|%s' % (m['sender'], m['ts'], (m.get('content') or '')[:120])
            if key in seen:
                continue
            seen.add(key)
            messages.append(m)
    messages.sort(key=lambda m: m.get('ts') or 0)
    contact = next((r['contact'] for r in valid if r['contact'] and r['contact'] not in ('联系人', '未知联系人')), '联系人')
    self_name = next((r['selfName'] for r in valid if r['selfName'] and r['selfName'] != '我'), '我')
    sources = list(dict.fromkeys(r['source'] for r in valid if r.get('source')))
    return {'contact': contact, 'selfName': self_name, 'source': ' + '.join(sources) if sources else '多平台整合', 'messages': messages}
