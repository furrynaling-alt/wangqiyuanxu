# py/server.py — 往栖缘叙 HTTP 后端（Python 版，端口 10086）
# 提供与 Node 版一致的 /api/* 端点 + 静态文件服务。数据写到 exe 旁 data/（可写）。
import json
import os
import sys
import re
import io
import uuid
import mimetypes
import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# 兼容：直接运行、开发运行、或 PyInstaller 打包后
_MEIPASS = getattr(sys, '_MEIPASS', None)
if getattr(sys, 'frozen', False):
    # PyInstaller：可执行文件所在目录（数据写这里）；public 在解包目录 _MEIPASS
    EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    APP_ROOT = EXE_DIR
    ROOT = _MEIPASS if _MEIPASS else EXE_DIR
    PUBLIC = os.path.join(ROOT, 'public')
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))        # py/ 目录
    APP_ROOT = os.path.dirname(ROOT)                          # 项目根
    PUBLIC = os.path.join(ROOT, '..', 'public')
PUBLIC = os.path.normpath(PUBLIC)
DATA_DIR = os.path.join(APP_ROOT, 'data')
CHATS_DIR = os.path.join(DATA_DIR, 'chats')
CHATS_JSON = os.path.join(DATA_DIR, 'chats.json')
SETTINGS_JSON = os.path.join(DATA_DIR, 'settings.json')
PORT = int(os.environ.get('PORT', '10086'))
NAME = '往栖缘叙'
VERSION = '0.1.1'

os.makedirs(CHATS_DIR, exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stats as statsLib
import importer as importerLib
import llm as llmLib
import prompts as promptsLib

def read_json(p, default):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def write_json(p, obj):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def get_registry():
    return read_json(CHATS_JSON, [])

def save_registry(r):
    write_json(CHATS_JSON, r)

CUSTOM_BG = os.path.join(DATA_DIR, 'custom_bg.png')
MEMORY_DIR = os.path.join(DATA_DIR, 'memory')
os.makedirs(MEMORY_DIR, exist_ok=True)
AVATAR_DIR = os.path.join(DATA_DIR, 'avatars')
os.makedirs(AVATAR_DIR, exist_ok=True)

def avatar_path(cid):
    return os.path.join(AVATAR_DIR, cid + '.png')

SELF_AVATAR = os.path.join(DATA_DIR, 'self_avatar.png')

def self_avatar_bytes():
    if os.path.exists(SELF_AVATAR):
        with open(SELF_AVATAR, 'rb') as f:
            return f.read()
    return None

def save_image(data_b64, out_path):
    # 把任意 base64 图片用 PIL 统一转成 PNG 保存（保证浏览器可渲染、格式兼容）
    import base64, io
    from PIL import Image
    if ',' in data_b64:
        data_b64 = data_b64.split(',', 1)[1]
    raw = base64.b64decode(data_b64)
    img = Image.open(io.BytesIO(raw))
    img = img.convert('RGBA')
    img.save(out_path, 'PNG')
    return True

def rename_record(cid, name):
    reg = get_registry()
    for c in reg:
        if c.get('id') == cid:
            c['displayName'] = name
            break
    save_registry(reg)

def memory_path(cid):
    return os.path.join(MEMORY_DIR, cid + '.json')

def load_memory(cid):
    try:
        with open(memory_path(cid), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'entries': []}

def save_memory(cid, mem):
    with open(memory_path(cid), 'w', encoding='utf-8') as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)

def memory_to_text(cid):
    mem = load_memory(cid)
    entries = mem.get('entries') or []
    if not entries:
        return ''
    lines = []
    for e in entries[-30:]:
        t = e.get('time') or ''
        s = e.get('summary') or ''
        if s:
            lines.append('- [%s] %s' % (t, s))
    return '\n'.join(lines)

# 规则版记忆提取：从用户消息 + 分身回复里抓可记住的关键信息
MEMORY_PATTERNS = [
    ('喜欢', r'我(?:比较|挺|很|超|最)?喜欢(.{0,20})'),
    ('讨厌', r'我(?:比较|挺|很|最)?(?:讨厌|不喜欢|烦)(.{0,20})'),
    ('在想', r'我?在(?:想|担心|烦|纠结)(.{0,25})'),
    ('期待', r'我(?:希望|盼|期待|想)(.{0,20})'),
]
def extract_memory(user_msg, reply):
    if not user_msg:
        return ''
    for tag, pat in MEMORY_PATTERNS:
        m = re.search(pat, user_msg)
        if m:
            val = m.group(1).strip()
            if val:
                return '%s：%s' % (tag, val[:40])
    # 兜底：抓用户说的重要内容句
    m = re.search(r'我(?:今天|最近|现在)(.{0,30})', user_msg)
    if m and len(m.group(1)) >= 4:
        return '近况：%s' % m.group(1)[:40]
    return ''

def append_memory(cid, summary):
    mem = load_memory(cid)
    entries = mem.get('entries') or []
    entries.append({'time': datetime.datetime.now().strftime('%m-%d %H:%M'), 'summary': summary})
    # 最多保留 100 条
    mem['entries'] = entries[-100:]
    save_memory(cid, mem)

def get_settings():
    return read_json(SETTINGS_JSON, {'base': llmLib.DEFAULT_BASE, 'model': llmLib.DEFAULT_MODEL, 'key': '', 'blur': 0, 'cloneSide': 'them', 'apis': [], 'skills': []})

def get_skills():
    return get_settings().get('skills') or []

def save_skills(skills):
    cur = get_settings()
    cur['skills'] = skills
    write_json(SETTINGS_JSON, cur)

def skills_to_text():
    skills = get_skills()
    if not skills:
        return ''
    lines = []
    for s in skills:
        if s.get('content'):
            lines.append('- %s：%s' % (s.get('name') or '技能', s.get('content')))
    return '\n'.join(lines)

def chat_path(cid):
    return os.path.join(CHATS_DIR, cid + '.json')

def analysis_path(cid):
    return os.path.join(CHATS_DIR, cid + '.analysis.md')

def load_chat(cid):
    p = chat_path(cid)
    if not os.path.exists(p):
        return None
    return read_json(p, None)

def compute_stats(record):
    return statsLib.compute_stats(record)

def sse_write(handler, obj):
    data = json.dumps(obj, ensure_ascii=False)
    handler.wfile.write(('data: %s\n\n' % data).encode('utf-8'))
    handler.wfile.flush()

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # 静默日志，避免刷屏
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', '0') or '0')
        if length <= 0:
            return ''
        return self.rfile.read(length).decode('utf-8', 'ignore')

    def _serve_static(self, url_path):
        rel = url_path
        if rel == '/':
            rel = '/index.html'
        rel = rel.lstrip('/')
        file_path = os.path.normpath(os.path.join(PUBLIC, rel))
        if not file_path.startswith(os.path.normpath(PUBLIC)):
            self._send_json(403, {'error': 'forbidden'})
            return
        if not os.path.exists(file_path):
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'404 Not Found')
            return
        mime = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        if mime == 'text/html':
            mime = 'text/html; charset=utf-8'
        with open(file_path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split('?')[0]
        if p.startswith('/api/status'):
            # 返回完整统计（含 scores 主动/被爱/冷淡），数据量通常快；用 Threading 服务避免阻塞
            reg = get_registry()
            chats = []
            for c in reg:
                try:
                    rec = load_chat(c.get('id'))
                    st = compute_stats(rec) if rec else None
                    chats.append({**c, 'contact': c.get('displayName') or c.get('contact'),
                                  'total': st['basic']['total_messages'] if st else 0,
                                  'dateRange': st['basic']['date_range'] if st else [],
                                  'myRatio': st['basic']['my_ratio'] if st else 0,
                                  'scores': st['scores'] if st else None,
                                  'hasAvatar': os.path.exists(avatar_path(c.get('id'))),
                                  'hasAnalysis': os.path.exists(analysis_path(c.get('id')))})
                except Exception:
                    chats.append(c)
            self._send_json(200, {'name': NAME, 'version': VERSION, 'chats': chats})
            return

        m = re.match(r'^/api/stats/([0-9a-f]+)$', p)
        if m:
            rec = load_chat(m.group(1))
            if not rec:
                self._send_json(404, {'error': '记录不存在'})
                return
            self._send_json(200, compute_stats(rec))
            return

        m_mem = re.match(r'^/api/memory/([0-9a-f]+)$', p)
        if m_mem:
            mem = load_memory(m_mem.group(1))
            self._send_json(200, mem)
            return

        if p.startswith('/api/self-avatar'):
            data = self_avatar_bytes()
            if not data:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'no avatar')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        m_av = re.match(r'^/api/avatar/([0-9a-f]+)$', p)
        if m_av:
            ap = avatar_path(m_av.group(1))
            if not os.path.exists(ap):
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'no avatar')
                return
            with open(ap, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if p.startswith('/api/views'):
            self._send_json(200, {'views': promptsLib.ANALYSIS_VIEWS})
            return

        if p.startswith('/api/history'):
            reg = get_registry()
            list_out = []
            for c in reg:
                rid = c.get('id')
                ap = analysis_path(rid)
                if os.path.exists(ap):
                    try:
                        with open(ap, 'r', encoding='utf-8') as f:
                            text = f.read()
                        list_out.append({'reportId': rid, 'id': rid, 'contact': c.get('contact'), 'name': 'AI 深度分析', 'date': datetime.datetime.fromtimestamp(os.path.getmtime(ap)).strftime('%Y-%m-%d %H:%M'), 'chars': len(text), 'fromAI': True})
                    except Exception:
                        pass
            self._send_json(200, {'list': list_out})
            return

        m = re.match(r'^/api/report/([0-9a-f]+)$', p)
        if m:
            ap = analysis_path(m.group(1))
            if not os.path.exists(ap):
                self._send_json(404, {'error': '报告不存在'})
                return
            with open(ap, 'r', encoding='utf-8') as f:
                text = f.read()
            self._send_json(200, {'id': m.group(1), 'text': text})
            return

        if p.startswith('/api/skills'):
            self._send_json(200, {'list': get_skills()})
            return

        if p.startswith('/api/settings'):
            s = get_settings()
            self._send_json(200, {**s, 'key': '已保存（点击可重新输入）' if s.get('key') else ''})
            return

        if p.startswith('/api/api-list'):
            s = get_settings()
            self._send_json(200, {'list': s.get('apis') or []})
            return

        if p.startswith('/custom-bg'):
            if not os.path.exists(CUSTOM_BG):
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b'no bg')
                return
            with open(CUSTOM_BG, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._serve_static(p)

    def do_POST(self):
        p = self.path.split('?')[0]
        if p.startswith('/api/import'):
            try:
                body = json.loads(self._read_body() or '{}')
                payload = body.get('payload')
                file_name = body.get('fileName') or ''
                fmt = body.get('format')
                if not fmt or fmt == 'auto':
                    fmt = importerLib.detect_format(payload, file_name)
                if not fmt:
                    self._send_json(400, {'error': '无法识别文件格式，请确认是 JSON 或带时间戳的文本'})
                    return
                record = importerLib.normalize(payload, fmt, file_name)
                if not record.get('messages'):
                    self._send_json(400, {'error': '没有解析到任何消息'})
                    return
                if len(record['messages']) < 5:
                    self._send_json(400, {'error': '消息太少（<5条），无法分析'})
                    return
                # 去重：相同联系人 + 来源 + 消息条数，且首末时间接近 → 视为重复，不重复导入
                n = len(record['messages'])
                c_contact = record.get('contact')
                c_source = record.get('source')
                ts0 = min(m.get('ts', 0) for m in record['messages'])
                ts1 = max(m.get('ts', 0) for m in record['messages'])
                reg_now = get_registry()
                dup = None
                for c in reg_now:
                    try:
                        rr = load_chat(c.get('id'))
                        if not rr or rr.get('contact') != c_contact or rr.get('source') != c_source:
                            continue
                        if len(rr.get('messages') or []) == n:
                            msg0 = min(m.get('ts', 0) for m in rr['messages'])
                            msg1 = max(m.get('ts', 0) for m in rr['messages'])
                            if abs(msg0 - ts0) < 300 and abs(msg1 - ts1) < 300:
                                dup = c.get('id')
                                break
                    except Exception:
                        continue
                if dup:
                    self._send_json(200, {'id': dup, 'contact': c_contact, 'source': c_source, 'total': n, 'days': 0, 'dateRange': [], 'duplicate': True})
                    return
                cid = uuid.uuid4().hex[:8]
                write_json(chat_path(cid), record)
                reg = get_registry()
                reg.append({'id': cid, 'contact': record.get('contact'), 'selfName': record.get('selfName'),
                            'source': record.get('source'), 'importedAt': datetime.datetime.utcnow().isoformat()})
                save_registry(reg)
                st = compute_stats(record)
                self._send_json(200, {'id': cid, 'contact': record.get('contact'), 'source': record.get('source'),
                                      'total': st['basic']['total_messages'], 'days': st['basic']['total_days'],
                                      'dateRange': st['basic']['date_range']})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/merge'):
            try:
                body = json.loads(self._read_body() or '{}')
                ids = body.get('ids') or []
                if len(ids) < 2:
                    self._send_json(400, {'error': '至少选择两个记录才能整合'})
                    return
                recs = [load_chat(cid) for cid in ids]
                if any(r is None for r in recs):
                    self._send_json(404, {'error': '记录不存在'})
                    return
                merged = importerLib.merge_records(recs)
                if not merged.get('messages'):
                    self._send_json(400, {'error': '没有可整合的消息'})
                    return
                cid = uuid.uuid4().hex[:8]
                write_json(chat_path(cid), merged)
                reg = get_registry()
                reg.append({'id': cid, 'contact': merged.get('contact'), 'selfName': merged.get('selfName'),
                            'source': merged.get('source'), 'importedAt': datetime.datetime.utcnow().isoformat()})
                save_registry([c for c in reg if c.get('id') not in ids])
                for old in ids:
                    for f in (chat_path(old), analysis_path(old)):
                        try:
                            if os.path.exists(f):
                                os.remove(f)
                        except Exception:
                            pass
                st = compute_stats(merged)
                self._send_json(200, {'id': cid, 'contact': merged.get('contact'), 'total': st['basic']['total_messages'],
                                      'days': st['basic']['total_days'], 'dateRange': st['basic']['date_range']})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/record/rename'):
            try:
                body = json.loads(self._read_body() or '{}')
                cid = body.get('id')
                name = (body.get('name') or '').strip()
                if not cid or not name:
                    self._send_json(400, {'error': '缺少 id 或名称'})
                    return
                rename_record(cid, name)
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/self-avatar-upload'):
            try:
                body = json.loads(self._read_body() or '{}')
                data = body.get('data') or ''
                if not data:
                    self._send_json(400, {'error': '缺少图片'})
                    return
                save_image(data, SELF_AVATAR)
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': '图片无效: ' + str(e)})
            return

        if p.startswith('/api/record/avatar'):
            try:
                body = json.loads(self._read_body() or '{}')
                cid = body.get('id')
                data = body.get('data') or ''
                if not cid or not data:
                    self._send_json(400, {'error': '缺少 id 或图片'})
                    return
                save_image(data, avatar_path(cid))
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': '图片无效: ' + str(e)})
            return

        if p.startswith('/api/skill-add'):
            try:
                body = json.loads(self._read_body() or '{}')
                skills = get_skills()
                skills.append({'id': 'sk_' + uuid.uuid4().hex[:6], 'name': body.get('name'), 'content': body.get('content')})
                save_skills(skills)
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/skill-del'):
            try:
                body = json.loads(self._read_body() or '{}')
                sid = body.get('id')
                save_skills([s for s in get_skills() if s.get('id') != sid])
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/api-save'):
            try:
                body = json.loads(self._read_body() or '{}')
                cur = get_settings()
                apis = cur.get('apis') or []
                new_id = 'api_' + uuid.uuid4().hex[:8]
                entry = {'id': new_id, 'base': body.get('base'), 'key': body.get('key') or '', 'model': body.get('model'), 'label': body.get('label') or (body.get('model') or 'API'), 'active': bool(body.get('makeActive'))}
                # 若非激活，则保持现有激活
                if not entry['active']:
                    entry['active'] = not any(a.get('active') for a in apis)
                # 设为当前：取消其他
                if entry['active']:
                    for a in apis:
                        a['active'] = False
                apis.append(entry)
                # 若这是第一个或设为当前，更新当前 base/key/model
                if entry['active']:
                    cur['base'] = entry['base']
                    cur['model'] = entry['model']
                    cur['key'] = entry['key']
                cur['apis'] = apis
                write_json(SETTINGS_JSON, cur)
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/api-set-active'):
            try:
                body = json.loads(self._read_body() or '{}')
                aid = body.get('id')
                cur = get_settings()
                apis = cur.get('apis') or []
                for a in apis:
                    a['active'] = (a.get('id') == aid)
                target = next((a for a in apis if a.get('id') == aid), None)
                if target:
                    cur['base'] = target.get('base')
                    cur['model'] = target.get('model')
                    cur['key'] = target.get('key') or ''
                cur['apis'] = apis
                write_json(SETTINGS_JSON, cur)
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/api-del'):
            try:
                body = json.loads(self._read_body() or '{}')
                aid = body.get('id')
                cur = get_settings()
                apis = cur.get('apis') or []
                apis = [a for a in apis if a.get('id') != aid]
                cur['apis'] = apis
                # 若删除的是当前活跃，回退到第一个（若有）
                if not any(a.get('active') for a in apis) and apis:
                    apis[0]['active'] = True
                    cur['base'] = apis[0].get('base')
                    cur['model'] = apis[0].get('model')
                    cur['key'] = apis[0].get('key') or ''
                write_json(SETTINGS_JSON, cur)
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/upload-bg'):
            try:
                body = json.loads(self._read_body() or '{}')
                data = body.get('data') or ''
                if ',' in data:
                    data = data.split(',', 1)[1]
                import base64
                buf = base64.b64decode(data)
                with open(CUSTOM_BG, 'wb') as f:
                    f.write(buf)
                self._send_json(200, {'ok': True, 'size': len(buf)})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/settings'):
            try:
                body = json.loads(self._read_body() or '{}')
                cur = get_settings()
                if body.get('key') in ('', None) and 'key' in cur:
                    body['key'] = cur['key']
                write_json(SETTINGS_JSON, {**cur, **{k: v for k, v in body.items() if k != 'key' or v}})
                self._send_json(200, {'ok': True})
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/analyze'):
            try:
                body = json.loads(self._read_body() or '{}')
                cid = body.get('id')
                view = body.get('view') or 'love'
                rec = load_chat(cid)
                if not rec:
                    self._send_json(404, {'error': '记录不存在'})
                    return
                st = compute_stats(rec)
                cfg = body.get('api') or get_settings()
                sys_p = promptsLib.build_analysis_system(view)
                user_p = promptsLib.build_analysis_user(rec, st)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                full = ''
                try:
                    def on_delta(d):
                        nonlocal full
                        full += d
                        sse_write(self, {'delta': d})
                    llmLib.chat(cfg.get('base'), cfg.get('key'), cfg.get('model'),
                                [{'role': 'system', 'content': sys_p}, {'role': 'user', 'content': user_p}],
                                temperature=0.6, on_delta=on_delta)
                    write_json(analysis_path(cid), {'_type': 'md', '_text': full})
                    # 分析报告存为 .md
                    with open(analysis_path(cid), 'w', encoding='utf-8') as f:
                        f.write(full)
                    sse_write(self, {'done': True})
                except Exception as e:
                    sse_write(self, {'error': str(e)})
                return
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        if p.startswith('/api/talk'):
            try:
                body = json.loads(self._read_body() or '{}')
                cid = body.get('id')
                mode = body.get('mode', 'advisor')
                message = body.get('message') or ''
                history = body.get('history') or []
                clone_side = body.get('cloneSide') or get_settings().get('cloneSide') or 'them'
                advisor_cat = body.get('advisorCat') or 'love'
                rec = load_chat(cid)
                if not rec:
                    self._send_json(404, {'error': '记录不存在'})
                    return
                cfg = body.get('api') or get_settings()
                st = compute_stats(rec)
                if mode == 'persona':
                    memory_text = memory_to_text(cid)
                    skills_text = skills_to_text()
                    system = promptsLib.build_persona_system(rec, st, {'cloneSide': clone_side, 'meName': rec.get('selfName') or '我', 'themName': rec.get('contact') or 'TA', 'memory': memory_text, 'skills': skills_text})
                else:
                    ap = analysis_path(cid)
                    analysis = ''
                    try:
                        if os.path.exists(ap):
                            with open(ap, 'r', encoding='utf-8') as f:
                                analysis = f.read()
                    except Exception:
                        analysis = ''
                    system = promptsLib.build_advisor_system(json.dumps(st, ensure_ascii=False)[:3500], analysis, advisor_cat)
                msgs = [{'role': 'system', 'content': system}] + list(history[-24:]) + [{'role': 'user', 'content': message}]
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                try:
                    def on_delta(d):
                        sse_write(self, {'delta': d})
                    full = llmLib.chat(cfg.get('base'), cfg.get('key'), cfg.get('model'), msgs, temperature=0.8, on_delta=on_delta)
                    sse_write(self, {'done': True})
                    # 数字分身：把本次可记住的信息写入记忆图谱（规则提取，不额外耗 API）
                    if mode == 'persona':
                        msum = extract_memory(user_msg=message, reply=full)
                        if msum:
                            append_memory(cid, msum)
                except Exception as e:
                    sse_write(self, {'error': str(e)})
                return
            except Exception as e:
                self._send_json(500, {'error': str(e)})
            return

        m = re.match(r'^/api/chats/([0-9a-f]+)$', p)
        if m:
            cid = m.group(1)
            reg = [c for c in get_registry() if c.get('id') != cid]
            save_registry(reg)
            for f in (chat_path(cid), analysis_path(cid)):
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass
            self._send_json(200, {'ok': True})
            return

        self._send_json(404, {'error': 'not found'})

    def do_DELETE(self):
        p = self.path
        m = re.match(r'^/api/chats/([0-9a-f]+)$', p)
        if m:
            cid = m.group(1)
            reg = [c for c in get_registry() if c.get('id') != cid]
            save_registry(reg)
            for f in (chat_path(cid), analysis_path(cid)):
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass
            self._send_json(200, {'ok': True})
            return
        self._send_json(404, {'error': 'not found'})

def run(host='127.0.0.1', port=None, ready_cb=None):
    port = port or PORT
    httpd = ThreadingHTTPServer((host, port), Handler)
    if ready_cb:
        ready_cb(port)
    print(' %s v%s 已启动  http://%s:%s' % (NAME, VERSION, host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__ == '__main__':
    run()
