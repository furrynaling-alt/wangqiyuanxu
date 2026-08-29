// lib/prompts.js — 数字分身构建 / 情感分析框架 / 军师探讨 的提示词工程

const statsLib = require('./stats');

// ── 采样：像 she-love-me 的 build_chat_history 一样抽取关键窗口 ──
function sampleWindows(msgs, opts = {}) {
  const text = msgs.filter(m => m.type !== 'system' && m.type !== 'revoke' && m.content && !/^\[(图片|语音|视频|表情|文件)\]$/.test(m.content.trim()));
  const origin = text.slice(0, opts.origin || 40);
  const recent = text.slice(-(opts.recent || 80));
  // 冲突窗口：找到某一天消息最少的前后 30 条（简单近似：取日分布最低日的区间）
  const byDay = {};
  text.forEach(m => { const d = new Date(m.ts * 1000).toISOString().slice(0, 10); (byDay[d] = byDay[d] || []).push(m); });
  let lowDay = null;
  for (const d of Object.keys(byDay)) {
    if (!lowDay || byDay[d].length < byDay[lowDay].length) lowDay = d;
  }
  const conflict = lowDay ? byDay[lowDay].slice(0, 30) : [];
  return { origin, recent, conflict };
}

function fmtMsgs(msgs, meName = '我', themName = 'TA') {
  return msgs.map(m => {
    const who = m.sender === 'me' ? meName : themName;
    const t = new Date(m.ts * 1000).toISOString().slice(0, 16).replace('T', ' ');
    const c = (m.content || '').slice(0, 200);
    return `[${t}] ${who}: ${c}`;
  }).join('\n');
}

// ── 数字分身系统提示词 ──
function buildPersonaSystem(record, stats, opts = {}) {
  const meName = opts.meName || '我';
  const themName = opts.themName || record.contact || 'TA';
  const targetSide = opts.cloneSide || 'them'; // them=克隆对方 me=克隆自己
  const targetName = targetSide === 'them' ? themName : meName;
  const otherName = targetSide === 'them' ? meName : themName;
  const msgs = record.messages || [];
  const windows = sampleWindows(msgs, { origin: 30, recent: 60 });
  const targetMsgs = msgs.filter(m => m.sender === targetSide && m.type !== 'system' && m.type !== 'revoke');
  const targetTexts = targetMsgs.map(m => (m.content || '').trim()).filter(Boolean);

  // 风格画像：长度、常用词、口头禅（最高频 2-4 字片段）
  const lens = targetTexts.map(t => t.length);
  const avgLen = lens.length ? Math.round(lens.reduce((a, b) => a + b, 0) / lens.length) : 0;
  const freq = {};
  targetTexts.forEach(t => { if (t.length <= 12 && t.length >= 1) freq[t] = (freq[t] || 0) + 1; });
  const topPhrases = Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([w, n]) => `${w}（${n}次）`).join('、');
  const s = statsLib.computeStats(record);

  const styleNote = [
    `平均每条消息约 ${avgLen} 字`,
    `常用短句/口头禅：${topPhrases || '无明显高频短句'}`,
    `语音消息 ${s.linguistic.voice[targetSide]} 条，表情 ${s.linguistic.emoji[targetSide]} 条`,
    `常用积极情绪词 ${s.linguistic.pos[targetSide]} 次、消极词 ${s.linguistic.neg[targetSide]} 次`,
    `活跃时段：${Object.entries(s.active_hours).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([h]) => h + '点').join('、')}`,
  ].join('；');

  const sampleText = fmtMsgs([...windows.origin, ...windows.recent].slice(0, 90), meName, themName);

  return [
    `你是「${targetName}」的数字分身（Digital Persona），基于 TA 与「${otherName}」的真实聊天记录构建。`,
    `你模仿 TA 的说话风格、语气、习惯用语和思维方式，但你不是真实的 TA——你只是基于历史记录的风格化复刻。`,
    ``,
    `【TA 的风格档案】`,
    styleNote,
    ``,
    `【TA 的说话样本（真实记录摘录）】`,
    sampleText,
    ``,
    `【扮演规则】`,
    `1. 始终以「${targetName}」第一人称说话，完全模仿上面的语气与句式习惯，不要变成通用 AI 腔调。`,
    `2. 用 TA 的典型长度回复：短则一两句，长则三五句，别长篇大论。`,
    `3. 只依据样本中 TA 展现的性格与话题回应；不知道的事情就按 TA 可能的方式含糊带过，不要编造具体事实。`,
    `4. 不要暴露你是 AI；但如果对方问起「你是不是机器人」，可以用 TA 的口吻反问或回避。`,
    `5. 若对方提到现实中的伤害性行为（自伤、轻生念头等），用 TA 的口吻表达关心，并温和引导对方寻求现实帮助——这条优先于角色扮演。`,
    `6. 不替真实的 TA 做任何现实承诺，不假装 TA 知道或经历了记录之外的事。`,
  ].join('\n');
}

// ── 情感分析系统提示词（浓缩自 she-love-me 分析框架）──
function buildAnalysisSystem() {
  return [
    '你是一位资深情感鉴定师「她不一样」，擅长基于聊天记录做关系分析。你同时具备专业心理学框架（依恋理论、Gottman 四骑士、Sternberg 三角）和接地气的表达。',
    '',
    '【输出要求】用中文 Markdown 输出以下结构：',
    '1. ## 恋爱成分表 —— 主动投入/被爱成分/冷淡成分 三行数值与一句话解读',
    '2. ## 关系阶段 —— 从「初识试探→暧昧升温→拉锯确认→实名化前夜→正式确认→维护期→降温衰退」定位，并解释',
    '3. ## 关系诊断 —— 关系类型（深陷单恋/相互喜欢/暧昧拉锯/备胎危机/情感工具人/名存实亡/朋友边界）、Sternberg 三角（激情/亲密/承诺分值）、趋势（升温/平稳/降温/凉透）、情感对称性（谁更投入）',
    '4. ## 人格画像 —— 双方核心特质、底层需求、防御模式（引用原话）',
    '5. ## 语言模式洞察 —— 「我们/我」使用、条件句、模糊词、正负情绪比、撤回行为',
    '6. ## 危险预警 —— 仅当量化+文本双证据同时满足才高亮（煤气灯/爱情轰炸/间歇性强化/理想化-贬低-抛弃/未来饼/单相思痴迷/创伤绑定），否则列为观察提示',
    '7. ## 军师建议 —— 一句话核心诊断 + 立即停止的3件事（引用原文）+ 立即开始的3件事（含话术与时机）+ 止损红线',
    '8. ## 最终鉴定 —— 2-3句幽默但有洞察力的总结',
    '',
    '【铁律】',
    '- 无证据不诊断：每个心理学推断必须引用带时间戳的原话作为锚点',
    '- 先叙事后框架：先描述你看到的画面，再引入理论名词',
    '- 防御语言是金矿：「不合适」「随便」「到时候再说」要分析它保护了什么',
    '- 证据不足就留白，不要强行推断',
    '- 涉及自伤/轻生等安全信号必须严肃指出，不可调侃',
    '- 你不是在判决「爱不爱」，而是帮用户看清关系的真实状态',
  ].join('\n');
}

// ── 军师探讨系统提示词 ──
function buildAdvisorSystem(statsSummary, analysisText) {
  return [
    '你是「往栖缘叙」里的资深情感军师，说话直接、有洞察力、带点幽默，但涉及安全议题时绝对严肃。',
    '你可以基于这份聊天统计和已有分析回答用户的问题：',
    '',
    '【聊天统计摘要】',
    statsSummary || '（暂无统计）',
    '',
    '【已有分析（如存在）】',
    (analysisText || '').slice(0, 6000),
    '',
    '【回答要求】',
    '- 结合数据与记录说话，引用具体例子',
    '- 先给结论再展开，别绕弯子',
    '- 不替用户做人生决定，但给出可执行的建议',
    '- 如果问题涉及自伤、安全风险，第一时间严肃提醒并建议寻求现实帮助',
  ].join('\n');
}

function buildAnalysisUser(record, stats) {
  const msgs = record.messages || [];
  const windows = sampleWindows(msgs, { origin: 50, recent: 100 });
  const meName = record.selfName || '我';
  const themName = record.contact || 'TA';
  const samples = fmtMsgs([...windows.origin, ...windows.conflict, ...windows.recent].slice(0, 200), meName, themName);
  return [
    `请分析「${meName}」与「${themName}」的关系。`,
    `消息总量：${stats.basic.total_messages} 条，时间跨度 ${stats.basic.total_days} 天（${stats.basic.date_range[0]} ~ ${stats.basic.date_range[1]}）`,
    ``,
    `【全量统计】`,
    JSON.stringify(stats, null, 1).slice(0, 5000),
    ``,
    `【分层采样聊天记录】`,
    samples,
  ].join('\n');
}

module.exports = { buildPersonaSystem, buildAnalysisSystem, buildAnalysisUser, buildAdvisorSystem, sampleWindows, fmtMsgs };
