// lib/llm.js — OpenAI 兼容 API 客户端（DeepSeek / 混元 / 任意 /v1 接口）
// 支持流式与非流式。Base URL 例: https://api.deepseek.com 或 https://api.deepseek.com/v1
//
// 【重要】本机 node 进程访问外网 HTTPS 会卡死（环境限制），因此默认经由
// lib/llm_bridge.py（Python 桥）发请求。若找不到 python，则回退到内置 fetch。

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const DEFAULT_BASE = 'https://api.deepseek.com';
const DEFAULT_MODEL = 'deepseek-chat';

// 尝试定位一个可用的 python（内置 runtime 优先，其次系统 python）
function findPython() {
  const candidates = [
    process.env.PYTHON_PATH,
    process.env.PYTHON,
    path.join(process.env.LOCALAPPDATA || '', '..', '..', 'Roaming', 'LobsterAI', 'runtimes', 'python-win', 'python.exe'),
    'python3',
    'python',
  ].filter(Boolean);
  for (const c of candidates) {
    try {
      if (c && c.includes('python') && (c.includes('\\') || c.includes('/')) && fs.existsSync(c)) return c;
    } catch {}
  }
  // 优先返回一个在任何环境都可能存在的命令名
  if (process.env.PYTHON) return process.env.PYTHON;
  return 'python';
}

function toChatURL(base) {
  let b = (base || DEFAULT_BASE).trim().replace(/\/+$/, '');
  if (!/\/chat\/completions$/.test(b)) {
    if (!/\/v1$/.test(b)) b += '/v1';
    b += '/chat/completions';
  }
  return b;
}

// ── 方式一：Python 桥（推荐，本机 node 出网卡死时的唯一可靠通道）──
function chatViaPython({ base, key, model, messages, temperature, onDelta, signal }, python) {
  return new Promise((resolve, reject) => {
    const url = toChatURL(base);
    const payload = JSON.stringify({ url, key, model, messages, temperature: temperature ?? 0.7 });
    let settled = false;
    const finish = (err, value) => { if (settled) return; settled = true; clearTimeout(timer); err ? reject(err) : resolve(value); };

    const timer = setTimeout(() => { if (!settled) { try { child.kill(); } catch {} finish(new Error('AI 请求超时（Python 桥）')); } }, 240000);

    let child;
    try {
      child = spawn(python, [path.join(__dirname, 'llm_bridge.py')], { stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (e) { finish(e); return; }

    let buf = '';
    let full = '';

    child.stdout.on('data', (d) => {
      buf += d.toString('utf8');
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        const t = line.trim();
        if (!t) continue;
        try {
          const j = JSON.parse(t);
          if (j.error) { finish(new Error(j.error)); return; }
          if (j.delta) { full += j.delta; onDelta && onDelta(j.delta); }
        } catch {}
      }
    });

    child.stderr.on('data', () => { /* 忽略桥错误，交由退出码处理 */ });

    child.on('close', (code) => {
      if (settled) return;
      if (code !== 0 && !full) { finish(new Error('AI 请求失败（Python 桥退出码 ' + code + '）')); return; }
      finish(null, full);
    });

    child.on('error', (err) => finish(err));

    if (signal) {
      if (signal.aborted) { try { child.kill(); } catch {} finish(new Error('aborted')); return; }
      signal.addEventListener('abort', () => { try { child.kill(); } catch {} finish(new Error('aborted')); });
    }

    child.stdin.write(payload);
    child.stdin.end();
  });
}

// ── 方式二：内置 fetch（回退，普通电脑可直连外网）──
async function chatViaFetch({ base, key, model, messages, temperature = 0.7, stream = false, onDelta, signal }) {
  if (!key) throw new Error('未配置 API Key，请在「设置」中填写');
  const url = toChatURL(base);
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key.trim()}` },
    body: JSON.stringify({ model: model || DEFAULT_MODEL, messages, temperature, stream }),
    signal,
  });
  if (!resp.ok) {
    const body = await resp.text().catch(() => '');
    throw new Error(`API 错误 ${resp.status}: ${body.slice(0, 300)}`);
  }
  if (!stream) {
    const data = await resp.json();
    return data.choices?.[0]?.message?.content || '';
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let b = '';
  let full = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    b += decoder.decode(value, { stream: true });
    const lines = b.split('\n');
    b = lines.pop();
    for (const line of lines) {
      const t = line.trim();
      if (!t.startsWith('data:')) continue;
      const payload = t.slice(5).trim();
      if (payload === '[DONE]') continue;
      try {
        const j = JSON.parse(payload);
        const delta = j.choices?.[0]?.delta?.content || '';
        if (delta) { full += delta; onDelta && onDelta(delta); }
      } catch {}
    }
  }
  return full;
}

async function chat(opts) {
  const py = findPython();
  // 优先用 Python 桥；失败则回退内置 fetch。
  try {
    const out = await chatViaPython(opts, py);
    return out;
  } catch (e) {
    if (String(e.message).includes('未配置 API Key')) throw e;
    try { return await chatViaFetch(opts); } catch (e2) { throw e; }
  }
}

module.exports = { chat, toChatURL, DEFAULT_BASE, DEFAULT_MODEL };
