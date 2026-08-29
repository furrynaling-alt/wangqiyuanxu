// 往栖缘叙 · 主服务 — 零依赖 Node HTTP 服务器
// 启动: node server.js  →  http://127.0.0.1:3000
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// 兼容 pkg 打包：snapshot 里只读的是代码+public；数据必须写在 exe 旁的真实磁盘。
const packaged = !!process.pkg;
const ROOT = __dirname;                 // snapshot 内（只读，含 public）
const APP_ROOT = packaged ? path.dirname(process.execPath) : __dirname;  // exe 所在真实目录
const PUBLIC = path.join(ROOT, 'public');
const DATA = path.join(APP_ROOT, 'data');
const CHATS = path.join(DATA, 'chats');
const REGISTRY = path.join(DATA, 'chats.json');
const SETTINGS = path.join(DATA, 'settings.json');
const PORT = Number(process.env.PORT || 3000);
const HOST = '127.0.0.1';
const VERSION = '0.1.0';
const NAME = '往栖缘叙';

fs.mkdirSync(CHATS, { recursive: true });

const importer = require('./lib/importer');
const statsLib = require('./lib/stats');
const llm = require('./lib/llm');
const prompts = require('./lib/prompts');

// ── 数据存取 ──
function readJSON(p, def) { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return def; } }
function writeJSON(p, obj) { fs.writeFileSync(p, JSON.stringify(obj, null, 2), 'utf8'); }
function getRegistry() { return readJSON(REGISTRY, []); }
function saveRegistry(r) { writeJSON(REGISTRY, r); }
function getSettings() { return readJSON(SETTINGS, { base: llm.DEFAULT_BASE, model: llm.DEFAULT_MODEL, key: '', blur: 55, cloneSide: 'them' }); }
function chatPath(id) { return path.join(CHATS, id + '.json'); }
function analysisPath(id) { return path.join(CHATS, id + '.analysis.md'); }

function loadChatRecord(id) {
  const p = chatPath(id);
  if (!fs.existsSync(p)) return null;
  return readJSON(p, null);
}

// ── 请求体读取 ──
function readBody(req, limit = 200 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on('data', (c) => { size += c.length; if (size > limit) { reject(new Error('请求体过大')); req.destroy(); return; } chunks.push(c); });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function sendJSON(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}

// ── 静态文件 ──
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.webp': 'image/webp', '.woff2': 'font/woff2', '.md': 'text/markdown; charset=utf-8' };
function serveStatic(req, res, urlPath) {
  let rel = decodeURIComponent(urlPath);
  if (rel === '/') rel = '/index.html';
  const file = path.normalize(path.join(PUBLIC, rel));
  if (!file.startsWith(PUBLIC)) return sendJSON(res, 403, { error: 'forbidden' });
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('404 Not Found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
    res.end(data);
  });
}

// ── 路由 ──
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const p = url.pathname;
  try {
    // API
    if (p === '/api/status' && req.method === 'GET') {
      const reg = getRegistry();
      const chats = reg.map(c => { try { const rec = loadChatRecord(c.id); const st = rec ? statsLib.computeStats(rec) : null; return { ...c, total: st ? st.basic.total_messages : 0, dateRange: st ? st.basic.date_range : [], myRatio: st ? st.basic.my_ratio : 0, scores: st ? st.scores : null, hasAnalysis: fs.existsSync(analysisPath(c.id)) }; } catch { return c; } });
      return sendJSON(res, 200, { name: NAME, version: VERSION, chats });
    }
    if (p === '/api/import' && req.method === 'POST') {
      const body = JSON.parse(await readBody(req));
      const payload = body.payload;
      const fmt = body.format === 'auto' || !body.format ? importer.detectFormat(payload, body.fileName || '') : body.format;
      if (!fmt) return sendJSON(res, 400, { error: '无法识别文件格式，请确认是 JSON 或带时间戳的文本' });
      const record = importer.normalize(payload, fmt, body.fileName || '');
      if (!record.messages || record.messages.length === 0) return sendJSON(res, 400, { error: '没有解析到任何消息' });
      if (record.messages.length < 5) return sendJSON(res, 400, { error: '消息太少（<5条），无法分析' });
      const id = crypto.randomBytes(4).toString('hex');
      writeJSON(chatPath(id), record);
      const reg = getRegistry();
      reg.push({ id, contact: record.contact, selfName: record.selfName, source: record.source, importedAt: new Date().toISOString() });
      saveRegistry(reg);
      const st = statsLib.computeStats(record);
      return sendJSON(res, 200, { id, contact: record.contact, source: record.source, total: st.basic.total_messages, days: st.basic.total_days, dateRange: st.basic.date_range });
    }
    if (p === '/api/merge' && req.method === 'POST') {
      const { ids } = JSON.parse(await readBody(req));
      if (!Array.isArray(ids) || ids.length < 2) return sendJSON(res, 400, { error: '至少选择两个记录才能整合' });
      const recs = ids.map(loadChatRecord);
      if (recs.some(r => !r)) return sendJSON(res, 404, { error: '记录不存在' });
      const merged = importer.mergeRecords(recs);
      if (!merged.messages.length) return sendJSON(res, 400, { error: '没有可整合的消息' });
      const id = crypto.randomBytes(4).toString('hex');
      writeJSON(chatPath(id), merged);
      const reg = getRegistry();
      reg.push({ id, contact: merged.contact, selfName: merged.selfName, source: merged.source, importedAt: new Date().toISOString() });
      // 移除被整合的源记录，避免重复堆积
      saveRegistry(reg.filter(c => !ids.includes(c.id)));
      for (const old of ids) { for (const f of [chatPath(old), analysisPath(old)]) { try { fs.unlinkSync(f); } catch {} } }
      const st = statsLib.computeStats(merged);
      return sendJSON(res, 200, { id, contact: merged.contact, total: st.basic.total_messages, days: st.basic.total_days, dateRange: st.basic.date_range });
    }
    const chatMatch = p.match(/^\/api\/chats\/([0-9a-f]+)$/);
    if (chatMatch && req.method === 'DELETE') {
      const id = chatMatch[1];
      const reg = getRegistry().filter(c => c.id !== id);
      saveRegistry(reg);
      for (const f of [chatPath(id), analysisPath(id)]) { try { fs.unlinkSync(f); } catch {} }
      return sendJSON(res, 200, { ok: true });
    }
    const statsMatch = p.match(/^\/api\/stats\/([0-9a-f]+)$/);
    if (statsMatch && req.method === 'GET') {
      const rec = loadChatRecord(statsMatch[1]);
      if (!rec) return sendJSON(res, 404, { error: '记录不存在' });
      return sendJSON(res, 200, statsLib.computeStats(rec));
    }
    if (p === '/api/analyze' && req.method === 'POST') {
      const { id, api } = JSON.parse(await readBody(req));
      const rec = loadChatRecord(id);
      if (!rec) return sendJSON(res, 404, { error: '记录不存在' });
      const st = statsLib.computeStats(rec);
      const cfg = api || getSettings();
      const sys = prompts.buildAnalysisSystem();
      const user = prompts.buildAnalysisUser(rec, st);
      res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
      let full = '';
      try {
        await llm.chat({ base: cfg.base, key: cfg.key, model: cfg.model, messages: [{ role: 'system', content: sys }, { role: 'user', content: user }], temperature: 0.6, stream: true, onDelta: (d) => { full += d; res.write(`data: ${JSON.stringify({ delta: d })}\n\n`); } });
        fs.writeFileSync(analysisPath(id), full, 'utf8');
        res.write(`data: ${JSON.stringify({ done: true })}\n\n`);
      } catch (e) {
        res.write(`data: ${JSON.stringify({ error: e.message })}\n\n`);
      }
      res.end();
      return;
    }
    if (p === '/api/talk' && req.method === 'POST') {
      const { id, mode, message, history, api, cloneSide } = JSON.parse(await readBody(req));
      const rec = loadChatRecord(id);
      if (!rec) return sendJSON(res, 404, { error: '记录不存在' });
      const cfg = api || getSettings();
      const st = statsLib.computeStats(rec);
      let system;
      if (mode === 'persona') {
        system = prompts.buildPersonaSystem(rec, st, { cloneSide: cloneSide || getSettings().cloneSide || 'them', meName: rec.selfName || '我', themName: rec.contact || 'TA' });
      } else {
        const analysis = fs.existsSync(analysisPath(id)) ? fs.readFileSync(analysisPath(id), 'utf8') : '';
        system = prompts.buildAdvisorSystem(JSON.stringify(st, null, 1).slice(0, 3500), analysis);
      }
      const msgs = [
        { role: 'system', content: system },
        ...(Array.isArray(history) ? history.slice(-24) : []),
        { role: 'user', content: message },
      ];
      res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
      try {
        await llm.chat({ base: cfg.base, key: cfg.key, model: cfg.model, messages: msgs, temperature: 0.8, stream: true, onDelta: (d) => res.write(`data: ${JSON.stringify({ delta: d })}\n\n`) });
        res.write(`data: ${JSON.stringify({ done: true })}\n\n`);
      } catch (e) {
        res.write(`data: ${JSON.stringify({ error: e.message })}\n\n`);
      }
      res.end();
      return;
    }
    if (p === '/api/settings' && req.method === 'GET') {
      const s = getSettings();
      return sendJSON(res, 200, { ...s, key: s.key ? '已保存（点击可重新输入）' : '' });
    }
    if (p === '/api/settings' && req.method === 'POST') {
      const body = JSON.parse(await readBody(req));
      const cur = getSettings();
      const next = { ...cur, ...body };
      if (body.key === '' || body.key === undefined) next.key = cur.key;
      writeJSON(SETTINGS, next);
      return sendJSON(res, 200, { ok: true });
    }
    // 静态
    if (req.method === 'GET') return serveStatic(req, res, p);
    return sendJSON(res, 404, { error: 'not found' });
  } catch (e) {
    sendJSON(res, 500, { error: e.message });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`\n  ${NAME} v${VERSION} 已启动`);
  console.log(`  ➜  http://${HOST}:${PORT}\n`);
});
