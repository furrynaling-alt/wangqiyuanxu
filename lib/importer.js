// lib/importer.js — 把各种聊天导出格式归一化为统一结构
// 统一结构: { contact, selfName, source, messages: [{sender:'me'|'them', content, ts(秒), type}] }

const fs = require('fs');
const path = require('path');

function detectFormat(payload, fileName = '') {
  const trimmed = (payload || '').trim();
  if (!trimmed) return null;
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    let obj = null;
    try { obj = JSON.parse(trimmed); } catch { return 'markdown'; }
    if (Array.isArray(obj)) {
      // WeFlow 通常是数组；也可能是纯消息数组
      const first = obj[0];
      if (first && typeof first === 'object') {
        if (first && ('isSend' in first || 'senderUsername' in first) && 'createTime' in first) return 'weflow';
        if ('sender' in first || 'fromUser' in first || 'message' in first || 'msg' in first) return 'weflow';
        if ('sender' in first && 'content' in first) return 'weflow';
        if ('local_id' in first || ('sender' in first && 'timestamp' in first && 'content' in first)) return 'normalized';
      }
      return 'markdown';
    }
    if (typeof obj === 'object') {
      if (obj.messages && Array.isArray(obj.messages)) {
        if (obj.metadata && obj.chatInfo) return 'qce';
        if (obj.weflow || (obj.session && obj.messages && 'createTime' in (obj.messages[0] || {}))) return 'weflow';
        if (obj.source || obj.bundle_dir) return 'normalized';
        if (Array.isArray(obj.messages) && obj.messages.length && 'isSend' in obj.messages[0]) return 'weflow';
        return 'generic';
      }
      if (obj.contact_username || obj.own_wxid) return 'normalized';
    }
    return 'generic';
  }
  // 逐行 [时间] 名字: 内容
  return 'markdown';
}

function normalize(payload, format, fileName = '') {
  if (format === 'qce') return fromQCE(payload);
  if (format === 'normalized') return fromNormalized(payload);
  if (format === 'weflow') return fromWeFlow(payload);
  if (format === 'markdown') return fromMarkdown(payload);
  if (format === 'generic') return fromGeneric(payload);
  throw new Error('无法识别的格式: ' + format);
}

// —— QCE 导出 (D:\wx-qq\QQQCS\friend_xxx.json) ——
function fromQCE(payload) {
  const obj = typeof payload === 'string' ? JSON.parse(payload) : payload;
  const chatInfo = obj.chatInfo || {};
  const selfUin = String(chatInfo.selfUin || chatInfo.selfUid || '');
  const messages = (obj.messages || []).map((m) => {
    const senderUin = String((m.sender || {}).uin || (m.sender || {}).uid || '');
    const isMe = senderUin === selfUin;
    let content = '';
    if (m.content && typeof m.content === 'object') {
      content = m.content.text || '';
      if (!content && m.content.elements) {
        content = m.content.elements.map((e) => (e.data && (e.data.text || e.data.value)) || '').filter(Boolean).join(' ');
      }
    } else if (typeof m.content === 'string') {
      content = m.content;
    }
    const ts = m.timestamp ? Math.floor(m.timestamp / 1000) : Math.floor(new Date(m.time).getTime() / 1000);
    let type = (m.type || 'text').toLowerCase();
    if (m.recalled) type = 'revoke';
    if (type === 'audio') type = 'voice';
    if (type === 'face' || type === 'sticker') type = 'emoji';
    if (type === 'system' || m.system) type = 'system';
    return { sender: isMe ? 'me' : 'them', content: content || `[${type}]`, ts: ts || 0, type };
  }).filter((m) => m.ts > 0);
  return {
    contact: chatInfo.name || chatInfo.peerName || '未知联系人',
    selfName: chatInfo.selfName || '',
    source: 'QCE导出',
    messages,
  };
}

// —— she-love-me 归一化 messages.json ——
function fromNormalized(payload) {
  const obj = typeof payload === 'string' ? JSON.parse(payload) : payload;
  const list = Array.isArray(obj) ? obj : obj.messages || [];
  const messages = list.map((m) => {
    const sender = m.sender === 'me' || m.sender === 'self' || m.sender === 0 || m.sender === '0' ? 'me' : 'them';
    let content = m.content;
    if (content && typeof content === 'object') content = content.text || JSON.stringify(content);
    let type = m.type || 'text';
    if (type === 'revoke') type = 'revoke';
    return { sender, content: String(content || `[${type}]`), ts: Number(m.timestamp) || 0, type };
  }).filter((m) => m.ts > 0);
  return {
    contact: obj.contact_display || obj.contact_username || '未知联系人',
    selfName: obj.own_wxid ? '我' : '',
    source: '归一化JSON',
    messages,
  };
}

// —— WeFlow 导出：顶层 {weflow, session, messages[], avatars}，消息含 isSend/senderDisplayName/createTime ——
function fromWeFlow(payload) {
  const obj = typeof payload === 'string' ? JSON.parse(payload) : payload;
  const list = Array.isArray(obj) ? obj : (obj.messages || []);
  const session = (!Array.isArray(obj) && obj.session) ? obj.session : {};
  const myWxid = session.wxid || '';
  const contact = session.nickname || session.displayName || session.remark || (session.type === '1' ? '我' : '联系人');
  let selfName = '我';
  // 从消息里找「我的昵称」：isSend=1 的 senderDisplayName 即是我
  for (const m of list) {
    if (typeof m.isSend === 'number' && m.isSend === 1 && m.senderDisplayName) { selfName = m.senderDisplayName; break; }
    if ((m.isSend === true || m.isSend === '1' || m.isSend === 1) && m.senderDisplayName) { selfName = m.senderDisplayName; break; }
  }
  const TYPE_MAP = { '文本消息': 'text', '图片消息': 'image', '语音消息': 'voice', '视频消息': 'video', '动画表情': 'emoji', '表情': 'emoji', '通话消息': 'system', '链接消息': 'link', '引用消息': 'text', '转账消息': 'system', '系统消息': 'system', '红包': 'system', '文件消息': 'file', '撤回消息': 'revoke' };
  const messages = (list || []).map((m) => {
    const isSend = m.isSend === 1 || m.isSend === true || m.isSend === '1';
    const sender = (myWxid && m.senderUsername === myWxid) ? 'me' : (isSend ? 'me' : 'them');
    let content = m.content || m.msg || m.message || m.text || '';
    if (content && typeof content === 'object') content = content.text || content.content || JSON.stringify(content);
    content = String(content).replace(/&#x20;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
    let ts = m.createTime || m.time || m.timestamp || m.ts || 0;
    if (typeof ts === 'string') ts = Date.parse(ts) / 1000;
    const rawType = m.type || '';
    let type = TYPE_MAP[rawType] || 'text';
    if (type === 'system' && /撤回|recalled|revoke/i.test(rawType)) type = 'revoke';
    return { sender, content: content || ('[' + (rawType || '消息') + ']'), ts: Math.floor(ts) || 0, type };
  }).filter((m) => m.ts > 0);
  return { contact: contact || '联系人', selfName, source: 'WeFlow导出', messages };
}

// —— 带时间戳的文本/Markdown: [2026-08-01 12:00] 名字: 内容 ——
function fromMarkdown(payload) {
  const lines = String(payload).split(/\r?\n/);
  const messages = [];
  let contact = '联系人';
  for (const line of lines) {
    const m = line.match(/^\s*[\[(](\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{0,2}:?\d{0,2}(?::\d{0,2})?)[\])]\s*(.+?)\s*[:：]\s*(.*)$/);
    if (!m) continue;
    const ts = Date.parse(m[1].replace(/\//g, '-').trim()) / 1000;
    if (!ts) continue;
    const name = m[2].trim();
    const content = m[3].trim();
    if (!content) continue;
    messages.push({ sender: /(我|me|self)/i.test(name) ? 'me' : 'them', content, ts: Math.floor(ts), type: 'text' });
  }
  return { contact, selfName: '我', source: '时间戳文本', messages };
}

// —— 兜底：任意带 messages 数组的 JSON ——
function fromGeneric(payload) {
  const obj = typeof payload === 'string' ? JSON.parse(payload) : payload;
  const list = Array.isArray(obj) ? obj : obj.messages || obj.data || [];
  const messages = list.map((m, i) => {
    const sender = (m.sender === 'me' || m.sender === 'self' || m.sender === 0 || m.sender === '0') ? 'me' : 'them';
    let content = m.content || m.text || m.msg || '';
    if (content && typeof content === 'object') content = content.text || JSON.stringify(content);
    let ts = m.timestamp || m.ts || m.time;
    if (typeof ts === 'string') ts = Date.parse(ts) / 1000;
    if (typeof ts === 'number' && ts > 1e12) ts = ts / 1000;
    return { sender, content: String(content || `[消息${i}]`), ts: Math.floor(ts) || 0, type: m.type || 'text' };
  }).filter((m) => m.ts > 0);
  return { contact: obj.contact || obj.name || '联系人', selfName: '我', source: '通用JSON', messages };
}

// —— 整合多个平台记录（同一联系人，来自 QQ/微信 等不同导出）——
// 策略：按时间升序合并消息；同 sender+ts+content 视为跨平台重复，去重；
// 平台信息拼接进 source；联系人取非空者。
function mergeRecords(records) {
  const valid = (records || []).filter(r => r && Array.isArray(r.messages) && r.messages.length);
  if (!valid.length) return { contact: '联系人', selfName: '我', source: '多平台整合', messages: [] };
  const seen = new Set();
  const messages = [];
  for (const rec of valid) {
    for (const m of (rec.messages || [])) {
      if (!m || !m.ts) continue;
      const key = `${m.sender}|${m.ts}|${(m.content || '').slice(0, 120)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      messages.push(m);
    }
  }
  messages.sort((a, b) => (a.ts || 0) - (b.ts || 0));
  const contact = valid.map(r => r.contact).find(c => c && c !== '联系人' && c !== '未知联系人') || '联系人';
  const selfName = valid.map(r => r.selfName).find(c => c && c !== '我') || '我';
  const sources = Array.from(new Set(valid.map(r => r.source).filter(Boolean)));
  return {
    contact,
    selfName,
    source: sources.length ? sources.join(' + ') : '多平台整合',
    messages,
  };
}

function loadChat(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  const fmt = detectFormat(raw, path.basename(filePath));
  return normalize(raw, fmt, path.basename(filePath));
}

module.exports = { detectFormat, normalize, loadChat, mergeRecords };
