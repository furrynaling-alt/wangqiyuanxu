// lib/stats.js — 聊天统计引擎（移植自 she-love-me stats_analyzer.py 核心指标）
// 输入: { messages: [{sender:'me'|'them', content, ts, type}] }
// 输出: 统计对象 + 三指数 (主动/被爱/冷淡)

const COLD_WORDS = ['嗯', '嗯嗯', '哦', '哦哦', '好吧', '好', '行', '呵呵', '随便', '无所谓', '？', '？', '哈', '哦豁', '知道了', '嗯呐'];
const GOODNIGHT_RE = /晚安|去睡|睡觉了|睡觉吧|要睡了|睡了哦|睡啦|先睡了|困了/;
const HEDGE_RE = /感觉|好像|也许|可能|大概|应该|或许|似乎/;
const CONDITIONAL_RE = /如果|要是|假如|只要|等你|若/;
const WE_RE = /我们|咱们/;
const I_RE = /我(?![们])/;
const POSITIVE_RE = /开心|喜欢|爱|想你|宝贝|好耶|嘿嘿|哈哈|棒|厉害|好看|可爱|甜|抱|亲|夸|笑死|好玩|漂亮|帅|温柔|想你|么么|摸摸|嘻嘻|不错|完美|期待|幸福|高兴|快乐/;
const NEGATIVE_RE = /难过|伤心|生气|烦|累|讨厌|失望|哭|痛|焦虑|压力|没爱|冷漠|不理|拉黑|分手|算了|没意思|孤独|难受|委屈|恨|气死|无语/;

function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }

function computeStats(record) {
  const msgs = (record.messages || []).filter(m => m && m.ts > 0).sort((a, b) => a.ts - b.ts);
  const total = msgs.length;
  const me = msgs.filter(m => m.sender === 'me');
  const them = msgs.filter(m => m.sender === 'them');
  const myCount = me.length, theirCount = them.length;
  const myRatio = total ? myCount / total : 0;

  // 基础
  const tsArr = msgs.map(m => m.ts);
  const dateRange = [tsArr[0], tsArr[tsArr.length - 1]];
  const days = tsArr.length > 1 ? Math.max(1, Math.round((tsArr[tsArr.length - 1] - tsArr[0]) / 86400)) : 1;
  const avgDaily = Math.round(total / days);

  // 发起（间隔 > 4 小时视为新对话，与原版口径一致）
  const starts = { me: 0, them: 0 };
  for (let i = 1; i < msgs.length; i++) {
    if (msgs[i].ts - msgs[i - 1].ts > 14400) starts[msgs[i].sender]++;
  }

  // 回复速度（对方上一条后多久回）
  const replySecs = { me: [], them: [] };
  for (let i = 1; i < msgs.length; i++) {
    const prev = msgs[i - 1], cur = msgs[i];
    if (prev.sender !== cur.sender) {
      const gap = cur.ts - prev.ts;
      if (gap >= 0 && gap < 86400) replySecs[cur.sender].push(gap);
    }
  }
  const avg = (arr) => arr.length ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length) : null;

  // 消息长度（文字）
  const textOf = (m) => (m.content || '').replace(/\[(图片|语音|视频|表情|文件|系统)\]/g, '').trim();
  const lens = { me: [], them: [] };
  msgs.forEach(m => {
    const t = textOf(m);
    if (t.length > 0 && m.type !== 'system' && m.type !== 'revoke') lens[m.sender].push(t.length);
  });
  const avgLen = (arr) => arr.length ? +(arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(1) : 0;

  // 连轰（同侧连续发 ≥3 条）
  const bomb = { me: { runs: 0, max: 0 }, them: { runs: 0, max: 0 } };
  let run = 0, runSender = null;
  const flush = () => { if (run >= 3 && runSender) bomb[runSender].runs++; };
  for (const m of msgs) {
    if (m.sender === runSender) run++;
    else { flush(); run = 1; runSender = m.sender; }
    if (runSender) bomb[runSender].max = Math.max(bomb[runSender].max, run);
  }
  flush();

  // 冷淡词
  const cold = { me: 0, them: 0, words: {} };
  const coldWordCount = {};
  msgs.forEach(m => {
    const t = textOf(m);
    if (!t) return;
    for (const w of COLD_WORDS) {
      if (t === w) { cold[m.sender]++; coldWordCount[w] = (coldWordCount[w] || 0) + 1; }
    }
  });

  // 晚安
  const gn = { me: 0, them: 0 };
  msgs.forEach(m => { if (GOODNIGHT_RE.test(textOf(m))) gn[m.sender]++; });

  // 语言特征
  const ling = { we: { me: 0, them: 0 }, i: { me: 0, them: 0 }, hedge: { me: 0, them: 0 }, cond: { me: 0, them: 0 }, pos: { me: 0, them: 0 }, neg: { me: 0, them: 0 }, revoke: { me: 0, them: 0 }, voice: { me: 0, them: 0 }, video: { me: 0, them: 0 }, emoji: { me: 0, them: 0 } };
  msgs.forEach(m => {
    const s = m.sender, t = textOf(m);
    if (m.type === 'revoke') { ling.revoke[s]++; return; }
    if (m.type === 'voice') { ling.voice[s]++; return; }
    if (m.type === 'video') { ling.video[s]++; return; }
    if (m.type === 'emoji') { ling.emoji[s]++; return; }
    if (!t) return;
    if (WE_RE.test(t)) ling.we[s]++;
    if (I_RE.test(t)) ling.i[s]++;
    if (HEDGE_RE.test(t)) ling.hedge[s]++;
    if (CONDITIONAL_RE.test(t)) ling.cond[s]++;
    if (POSITIVE_RE.test(t)) ling.pos[s]++;
    if (NEGATIVE_RE.test(t)) ling.neg[s]++;
  });

  // 时段 & 每日
  const activeHours = {};
  const dailyTrend = {};
  msgs.forEach(m => {
    const d = new Date(m.ts * 1000);
    const h = d.getHours();
    activeHours[h] = (activeHours[h] || 0) + 1;
    const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    dailyTrend[day] = (dailyTrend[day] || 0) + 1;
  });

  // 消息类型分布
  const types = {};
  msgs.forEach(m => { types[m.type || 'text'] = (types[m.type || 'text'] || 0) + 1; });

  // ── 三指数（近似 she-love-me 分数，量级校准）──
  const myStartRatio = (starts.me + starts.them) ? starts.me / (starts.me + starts.them) : 0.5;
  const myColdRatio = myCount ? cold.me / myCount : 0;
  const theirColdRatio = theirCount ? cold.them / theirCount : 0;
  const myBombNorm = clamp(bomb.me.runs / Math.max(1, myCount) * 100, 0, 30) / 30;   // 0..1
  const myLenNorm = clamp(avgLen(lens.me) / 30, 0, 1);
  const theirVoiceNorm = clamp(ling.voice.them / 10, 0, 1);
  const theirStartNorm = clamp((starts.them) / Math.max(1, starts.me + starts.them) * 2, 0, 1); // 0..1
  const myAffectionNorm = clamp(ling.pos.me / Math.max(1, myCount) * 20, 0, 1);
  const theirAffectionNorm = clamp(ling.pos.them / Math.max(1, theirCount) * 20, 0, 1);

  const simp = Math.round(clamp(
    myRatio * 42 +
    myStartRatio * 20 +
    myBombNorm * 30 +
    myLenNorm * 15 +
    myAffectionNorm * 5 +
    (gn.me > 0 ? 5 : 0),
    0, 100));
  const loved = Math.round(clamp(
    theirStartNorm * 30 +
    theirAffectionNorm * 18 +
    theirVoiceNorm * 12 +
    (1 - Math.min(1, theirColdRatio * 20)) * 10 +
    (gn.them > 0 ? 5 : 0),
    0, 100));
  const coldIndex = Math.round(clamp(
    theirColdRatio * 260 +
    (1 - Math.min(1, theirAffectionNorm)) * 5,
    0, 100));

  return {
    contact: record.contact || '联系人',
    selfName: record.selfName || '我',
    source: record.source || '',
    basic: {
      total_messages: total, my_messages: myCount, their_messages: theirCount,
      my_ratio: +myRatio.toFixed(3), their_ratio: +(1 - myRatio).toFixed(3),
      date_range: dateRange.map(t => new Date(t * 1000).toISOString().slice(0, 10)),
      total_days: days, avg_daily: avgDaily,
    },
    initiative: { my_starts: starts.me, their_starts: starts.them, my_start_ratio: +myStartRatio.toFixed(3) },
    reply_speed: {
      my_avg_seconds: avg(replySecs.me), their_avg_seconds: avg(replySecs.them),
      my_avg_human: human(avg(replySecs.me)), their_avg_human: human(avg(replySecs.them)),
    },
    message_length: { my_avg_chars: avgLen(lens.me), their_avg_chars: avgLen(lens.them) },
    bombing: { my_bomb_count: bomb.me.runs, their_bomb_count: bomb.them.runs, my_max_consecutive: bomb.me.max, their_max_consecutive: bomb.them.max },
    cold_response: { my_cold_count: cold.me, their_cold_count: cold.them, cold_words: coldWordCount },
    goodnight: gn,
    linguistic: ling,
    active_hours: activeHours,
    daily_trend: dailyTrend,
    message_types: types,
    scores: { simp_index: simp, loved_index: loved, cold_index: coldIndex },
  };
}

function human(sec) {
  if (sec == null) return '无数据';
  if (sec < 60) return sec + ' 秒';
  if (sec < 3600) return Math.round(sec / 60) + ' 分钟';
  return (sec / 3600).toFixed(1) + ' 小时';
}

module.exports = { computeStats };
