# py/prompts.py — 数字分身 / 情感分析框架 / 军师探讨 提示词工程（移植自 lib/prompts.js）
import json
import datetime
import re
import stats as statsLib

def sample_windows(msgs, origin=40, recent=80):
    text = [m for m in msgs if m.get('type') not in ('system', 'revoke')
            and m.get('content') and not re.match(r'^\[(图片|语音|视频|表情|文件)\]$', (m.get('content') or '').strip())]
    o = text[:origin]
    r = text[-recent:]
    by_day = {}
    for m in text:
        d = datetime.datetime.fromtimestamp(m['ts']).strftime('%Y-%m-%d')
        by_day.setdefault(d, []).append(m)
    low_day = min(by_day, key=lambda d: len(by_day[d])) if by_day else None
    conflict = by_day[low_day][:30] if low_day else []
    return {'origin': o, 'recent': r, 'conflict': conflict}

def fmt_msgs(msgs, me_name='我', them_name='TA'):
    lines = []
    for m in msgs:
        who = me_name if m.get('sender') == 'me' else them_name
        t = datetime.datetime.fromtimestamp(m['ts']).strftime('%Y-%m-%d %H:%M')
        c = (m.get('content') or '')[:200]
        lines.append('[%s] %s: %s' % (t, who, c))
    return '\n'.join(lines)

def build_persona_system(record, stats, opts=None):
    opts = opts or {}
    me_name = opts.get('meName') or '我'
    them_name = opts.get('themName') or record.get('contact') or 'TA'
    target_side = opts.get('cloneSide') or 'them'
    target_name = them_name if target_side == 'them' else me_name
    other_name = me_name if target_side == 'them' else them_name
    memory_text = opts.get('memory') or ''   # 长期记忆图谱文本
    skills_text = opts.get('skills') or ''    # 用户自定义技能/设定
    msgs = record.get('messages') or []
    windows = sample_windows(msgs, 30, 60)
    target_msgs = [m for m in msgs if m.get('sender') == target_side and m.get('type') not in ('system', 'revoke')]
    target_texts = [(m.get('content') or '').strip() for m in target_msgs if (m.get('content') or '').strip()]

    lens = [len(t) for t in target_texts]
    avg_len = round(sum(lens) / len(lens)) if lens else 0
    freq = {}
    for t in target_texts:
        if 1 <= len(t) <= 12:
            freq[t] = freq.get(t, 0) + 1
    top_phrases = '、'.join('%s（%d次）' % (w, n) for w, n in sorted(freq.items(), key=lambda x: -x[1])[:12]) or '无明显高频短句'
    s = statsLib.compute_stats(record)

    style_note = '；'.join([
        '平均每条消息约 %d 字' % avg_len,
        '常用短句/口头禅：%s' % top_phrases,
        '语音消息 %d 条，表情 %d 条' % (s['linguistic']['voice'][target_side], s['linguistic']['emoji'][target_side]),
        '常用积极情绪词 %d 次、消极词 %d 次' % (s['linguistic']['pos'][target_side], s['linguistic']['neg'][target_side]),
        '活跃时段：%s' % '、'.join('%s点' % h for h, _ in sorted(s['active_hours'].items(), key=lambda x: -x[1])[:3]),
    ])

    sample_text = fmt_msgs((windows['origin'] + windows['recent'])[:90], me_name, them_name)
    return '\n'.join([
        '你是「%s」的数字分身（Digital Persona），基于 TA 与「%s」的真实聊天记录构建。' % (target_name, other_name),
        '你模仿 TA 的说话风格、语气、习惯用语和思维方式，但你不是真实的 TA——你只是基于历史记录的风格化复刻。',
        '',
        '【TA 的风格档案】',
        style_note,
        '',
        '【TA 的说话样本（真实记录摘录）】',
        sample_text,
        '',
        '【长期记忆（你记得的过往，务必自然地引用，别生硬罗列）】',
        memory_text or '（暂无积累的记忆）',
        '',
        '【你的技能与设定（用户给你的本领，遵守这些规则）】',
        skills_text or '（无）',
        '',
        '【扮演规则】',
        '1. 始终以「%s」第一人称说话，完全模仿上面的语气与句式习惯，不要变成通用 AI 腔调。' % target_name,
        '2. 用 TA 的典型长度回复：短则一两句，长则三五句，别长篇大论。',
        '3. 只依据样本中 TA 展现的性格与话题回应；不知道的事情就按 TA 可能的方式含糊带过，不要编造具体事实。',
        '4. 不要暴露你是 AI；但如果对方问起「你是不是机器人」，可以用 TA 的口吻反问或回避。',
        '5. 若对方提到现实中的伤害性行为（自伤、轻生念头等），用 TA 的口吻表达关心，并温和引导对方寻求现实帮助——这条优先于角色扮演。',
        '6. 不替真实的 TA 做任何现实承诺，不假装 TA 知道或经历了记录之外的事。',
    ])

# 分析视角中文名（供前端/后端选择）
ANALYSIS_VIEWS = {
    'love': '情感军师',
    'boss': '老板分析',
    'bro': '兄弟分析',
    'lgbt': '同性恋分析',
    'normal': '普通情感',
    'deep': '深度思考',
}

def build_analysis_system(view='love'):
    base = [
        '',
        '【输出要求】用中文 Markdown 输出：',
        '1. ## 核心判断 —— 一句话说清这段关系的本质',
        '2. ## 证据链 —— 引用带时间戳的原话支撑你的判断（必写）',
        '3. ## 冷分数值 —— 用 0-100 给关键维度打分',
        '4. ## 行动建议 —— 3 件应立即做的事 + 3 件应立即停的事（含话术与时机）',
        '5. ## 风险提示 —— 潜在隐患或安全信号（如有）',
        '',
        '【铁律】',
        '- 无证据不诊断：每个结论必须引用带时间戳的原话作为锚点',
        '- 先叙事后框架：先描述你看到的画面，再引入理论名词',
        '- 证据不足就留白，不要强行推断',
        '- 涉及自伤/轻生等安全信号必须严肃指出，不可调侃',
    ]
    if view == 'boss':
        head = [
            '你是职场生存分析师「老江湖」，专门帮打工人判断老板值不值得跟、要不要跑路。看聊天记录里老板的态度、PUA、承诺兑现、画饼程度。',
            '【本视角重点】老板 PUA 话术识别、画饼 vs 真兑现、工资/对待是否公平、什么时候该跑路。',
        ]
        return '\n'.join(head + base)
    if view == 'bro':
        head = [
            '你是「真心话鉴定师」，专门判断兄弟是真心兄弟还是虚情假意（俗话的"倩倩/塑料兄弟"）。从借钱、患难、背后捅刀、关键时刻消失等角度。',
            '【本视角重点】谁是掏心掏肺、谁是利益往来、谁总在需要时才出现、这份交情值得投入多少。',
        ]
        return '\n'.join(head + base)
    if view == 'lgbt':
        head = [
            '你是「彩虹情感分析师」，针对同性恋关系做分析。理解同性关系特有的困境：出柜压力、隐蔽性、对未来共同生活的焦虑、社会认同对关系的影响。',
            '【本视角重点】关系里的安全感、被看见的渴望、公开程度对关系的影响、两人对"未来"的共同想象是否一致。',
        ]
        return '\n'.join(head + base)
    if view == 'deep':
        head = [
            '你是「深度思考者」，不局限于感情，而是把这段人际互动放在更大框架里：需求、防御、创伤、成长、人性。用哲学和心理学的视角做深层剖析。',
            '【本视角重点】这段关系折射出彼此的什么需求与恐惧？表面行为背后的深层逻辑？从这个经历里能成长什么？',
        ]
        return '\n'.join(head + base)
    # 默认：love / normal 情感
    head = [
        '你是一位资深情感鉴定师「她不一样」，擅长基于聊天记录做关系分析。你同时具备专业心理学框架（依恋理论、Gottman 四骑士、Sternberg 三角）和接地气的表达。',
        '【输出结构】恋爱成分表 / 关系阶段 / 关系诊断 / 人格画像 / 语言模式洞察 / 危险预警 / 军师建议 / 最终鉴定。',
    ]
    return '\n'.join(head + base)

ADVISOR_CATS = {
    'love': '真心军师',
    'lgbt': '同性恋军师',
    'boss': '老板军师',
    'bro': '兄弟军师',
    'deep': '深度军师',
}

def build_advisor_system(stats_summary, analysis_text, category='love'):
    persona = {
        'love': '你是「往栖缘叙」里的资深真心军师，专看情感关系，说话直接、有洞察力、带点幽默。',
        'lgbt': '你是「往栖缘叙」里的同性恋专属军师，理解同性关系特有的出柜压力、隐蔽性、对未来共同生活的焦虑，共情且专业。',
        'boss': '你是「往栖缘叙」里的老板军师（老江湖），专门帮打工人判断老板值不值得跟、要不要跑路，识别PUA和画饼。',
        'bro': '你是「往栖缘叙」里的兄弟真心鉴定师，判断兄弟是真心兄弟还是塑料/倩倩兄弟。',
        'deep': '你是「往栖缘叙」里的深度军师，不局限感情，用更大框架剖析需求、防御、创伤、成长与人性的深层逻辑。',
    }[category or 'love']
    return '\n'.join([
        persona,
        '你可以基于这份聊天统计和已有分析回答用户的问题：',
        '',
        '【聊天统计摘要】',
        stats_summary or '（暂无统计）',
        '',
        '【已有分析（如存在）】',
        (analysis_text or '')[:6000],
        '',
        '【回答要求】',
        '- 结合数据与记录说话，引用具体例子',
        '- 先给结论再展开，别绕弯子',
        '- 不替用户做人生决定，但给出可执行的建议',
        '- 如果问题涉及自伤、安全风险，第一时间严肃提醒并建议寻求现实帮助',
    ])

def build_analysis_user(record, stats):
    msgs = record.get('messages') or []
    windows = sample_windows(msgs, 50, 100)
    me_name = record.get('selfName') or '我'
    them_name = record.get('contact') or 'TA'
    samples = fmt_msgs((windows['origin'] + windows['conflict'] + windows['recent'])[:200], me_name, them_name)
    return '\n'.join([
        '请分析「%s」与「%s」的关系。' % (me_name, them_name),
        '消息总量：%d 条，时间跨度 %d 天（%s ~ %s）' % (stats['basic']['total_messages'], stats['basic']['total_days'], stats['basic']['date_range'][0], stats['basic']['date_range'][1]),
        '',
        '【全量统计】',
        json.dumps(stats, ensure_ascii=False, indent=1)[:5000],
        '',
        '【分层采样聊天记录】',
        samples,
    ])
