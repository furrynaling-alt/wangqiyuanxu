# py/stats.py — 聊天统计引擎（移植自 Node lib/stats.js）
# 输入: {messages: [{sender:'me'|'them', content, ts, type}]}
# 输出: 统计对象 + 三指数 (主动/被爱/冷淡)

import re

COLD_WORDS = ['嗯','嗯嗯','哦','哦哦','好吧','好','行','呵呵','随便','无所谓','？','哈','哦豁','知道了','嗯呐']
GOODNIGHT_RE = re.compile(r'晚安|去睡|睡觉了|睡觉吧|要睡了|睡了哦|睡啦|先睡了|困了')
HEDGE_RE = re.compile(r'感觉|好像|也许|可能|大概|应该|或许|似乎')
CONDITIONAL_RE = re.compile(r'如果|要是|假如|只要|等你|若')
WE_RE = re.compile(r'我们|咱们')
I_RE = re.compile(r'我(?![们])')
POSITIVE_RE = re.compile(r'开心|喜欢|爱|想你|宝贝|好耶|嘿嘿|哈哈|棒|厉害|好看|可爱|甜|抱|亲|夸|笑死|好玩|漂亮|帅|温柔|想你|么么|摸摸|嘻嘻|不错|完美|期待|幸福|高兴|快乐')
NEGATIVE_RE = re.compile(r'难过|伤心|生气|烦|累|讨厌|失望|哭|痛|焦虑|压力|没爱|冷漠|不理|拉黑|分手|算了|没意思|孤独|难受|委屈|恨|气死|无语')

def clamp(n, lo, hi):
    return max(lo, min(hi, n))

def text_of(content):
    return re.sub(r'\[(图片|语音|视频|表情|文件|系统)\]', '', content or '').strip()

def human(sec):
    if sec is None:
        return '无数据'
    if sec < 60:
        return str(sec) + ' 秒'
    if sec < 3600:
        return str(round(sec / 60)) + ' 分钟'
    return '%.1f' % (sec / 3600) + ' 小时'

def compute_stats(record):
    msgs = [m for m in (record.get('messages') or []) if m and m.get('ts')]
    msgs.sort(key=lambda m: m['ts'])
    total = len(msgs)
    me = [m for m in msgs if m.get('sender') == 'me']
    them = [m for m in msgs if m.get('sender') == 'them']
    my_count, their_count = len(me), len(them)
    my_ratio = (my_count / total) if total else 0

    ts_arr = [m['ts'] for m in msgs]
    date_range = [ts_arr[0], ts_arr[-1]] if ts_arr else []
    days = max(1, round((ts_arr[-1] - ts_arr[0]) / 86400)) if len(ts_arr) > 1 else 1
    avg_daily = round(total / days) if days else 0

    starts = {'me': 0, 'them': 0}
    for i in range(1, len(msgs)):
        if msgs[i]['ts'] - msgs[i-1]['ts'] > 14400:
            starts[msgs[i]['sender']] += 1

    reply_secs = {'me': [], 'them': []}
    for i in range(1, len(msgs)):
        prev, cur = msgs[i-1], msgs[i]
        if prev['sender'] != cur['sender']:
            gap = cur['ts'] - prev['ts']
            if 0 <= gap < 86400:
                reply_secs[cur['sender']].append(gap)
    def avg(arr):
        return round(sum(arr) / len(arr)) if arr else None

    lens = {'me': [], 'them': []}
    for m in msgs:
        t = text_of(m.get('content')) if m.get('content') else ''
        if t and m.get('type') not in ('system', 'revoke'):
            lens[m.get('sender')].append(len(t))
    def avg_len(arr):
        return round(sum(arr) / len(arr), 1) if arr else 0

    bomb = {'me': {'runs': 0, 'max': 0}, 'them': {'runs': 0, 'max': 0}}
    run, run_sender = 0, None
    def flush():
        if run >= 3 and run_sender:
            bomb[run_sender]['runs'] += 1
    for m in msgs:
        if m['sender'] == run_sender:
            run += 1
        else:
            flush(); run = 1; run_sender = m['sender']
        if run_sender:
            bomb[run_sender]['max'] = max(bomb[run_sender]['max'], run)
    flush()

    cold = {'me': 0, 'them': 0, 'words': {}}
    cold_word_count = {}
    for m in msgs:
        t = text_of(m.get('content')) if m.get('content') else ''
        if not t:
            continue
        for w in COLD_WORDS:
            if t == w:
                cold[m['sender']] += 1
                cold_word_count[w] = cold_word_count.get(w, 0) + 1

    gn = {'me': 0, 'them': 0}
    for m in msgs:
        if GOODNIGHT_RE.search(text_of(m.get('content')) if m.get('content') else ''):
            gn[m['sender']] += 1

    ling = {'we': {'me': 0, 'them': 0}, 'i': {'me': 0, 'them': 0}, 'hedge': {'me': 0, 'them': 0},
            'cond': {'me': 0, 'them': 0}, 'pos': {'me': 0, 'them': 0}, 'neg': {'me': 0, 'them': 0},
            'revoke': {'me': 0, 'them': 0}, 'voice': {'me': 0, 'them': 0}, 'video': {'me': 0, 'them': 0},
            'emoji': {'me': 0, 'them': 0}}
    for m in msgs:
        s = m['sender']
        t = text_of(m.get('content')) if m.get('content') else ''
        mt = m.get('type')
        if mt == 'revoke':
            ling['revoke'][s] += 1; continue
        if mt == 'voice':
            ling['voice'][s] += 1; continue
        if mt == 'video':
            ling['video'][s] += 1; continue
        if mt == 'emoji':
            ling['emoji'][s] += 1; continue
        if not t:
            continue
        if WE_RE.search(t): ling['we'][s] += 1
        if I_RE.search(t): ling['i'][s] += 1
        if HEDGE_RE.search(t): ling['hedge'][s] += 1
        if CONDITIONAL_RE.search(t): ling['cond'][s] += 1
        if POSITIVE_RE.search(t): ling['pos'][s] += 1
        if NEGATIVE_RE.search(t): ling['neg'][s] += 1

    active_hours = {}
    daily_trend = {}
    for m in msgs:
        d = m['ts'] * 1000
        import datetime
        dt = datetime.datetime.fromtimestamp(m['ts'])
        h = dt.hour
        active_hours[h] = active_hours.get(h, 0) + 1
        day = dt.strftime('%Y-%m-%d')
        daily_trend[day] = daily_trend.get(day, 0) + 1

    types = {}
    for m in msgs:
        t = m.get('type') or 'text'
        types[t] = types.get(t, 0) + 1

    my_start_ratio = (starts['me'] / (starts['me'] + starts['them'])) if (starts['me'] + starts['them']) else 0.5
    my_cold_ratio = (cold['me'] / my_count) if my_count else 0
    their_cold_ratio = (cold['them'] / their_count) if their_count else 0
    my_bomb_norm = clamp((bomb['me']['runs'] / max(1, my_count) * 100), 0, 30) / 30
    my_len_norm = clamp(avg_len(lens['me']) / 30, 0, 1)
    their_voice_norm = clamp(ling['voice']['them'] / 10, 0, 1)
    their_start_norm = clamp((starts['them']) / max(1, starts['me'] + starts['them']) * 2, 0, 1)
    my_aff_norm = clamp(ling['pos']['me'] / max(1, my_count) * 20, 0, 1)
    their_aff_norm = clamp(ling['pos']['them'] / max(1, their_count) * 20, 0, 1)

    simp = round(clamp(my_ratio * 42 + my_start_ratio * 20 + my_bomb_norm * 30 + my_len_norm * 15 + my_aff_norm * 5 + (5 if gn['me'] > 0 else 0), 0, 100))
    loved = round(clamp(their_start_norm * 30 + their_aff_norm * 18 + their_voice_norm * 12 + (1 - min(1, their_cold_ratio * 20)) * 10 + (5 if gn['them'] > 0 else 0), 0, 100))
    cold_index = round(clamp(their_cold_ratio * 260 + (1 - min(1, their_aff_norm)) * 5, 0, 100))

    return {
        'contact': record.get('contact') or '联系人',
        'selfName': record.get('selfName') or '我',
        'source': record.get('source') or '',
        'basic': {
            'total_messages': total, 'my_messages': my_count, 'their_messages': their_count,
            'my_ratio': round(my_ratio, 3), 'their_ratio': round(1 - my_ratio, 3),
            'date_range': [datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d') for t in date_range],
            'total_days': days, 'avg_daily': avg_daily,
        },
        'initiative': {'my_starts': starts['me'], 'their_starts': starts['them'], 'my_start_ratio': round(my_start_ratio, 3)},
        'reply_speed': {
            'my_avg_seconds': avg(reply_secs['me']), 'their_avg_seconds': avg(reply_secs['them']),
            'my_avg_human': human(avg(reply_secs['me'])), 'their_avg_human': human(avg(reply_secs['them'])),
        },
        'message_length': {'my_avg_chars': avg_len(lens['me']), 'their_avg_chars': avg_len(lens['them'])},
        'bombing': {'my_bomb_count': bomb['me']['runs'], 'their_bomb_count': bomb['them']['runs'],
                    'my_max_consecutive': bomb['me']['max'], 'their_max_consecutive': bomb['them']['max']},
        'cold_response': {'my_cold_count': cold['me'], 'their_cold_count': cold['them'], 'cold_words': cold_word_count},
        'goodnight': gn,
        'linguistic': ling,
        'active_hours': active_hours,
        'daily_trend': daily_trend,
        'message_types': types,
        'scores': {'simp_index': simp, 'loved_index': loved, 'cold_index': cold_index},
    }
