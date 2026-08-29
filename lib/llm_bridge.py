# lib/llm_bridge.py — 供 node 调用的 OpenAI 兼容 HTTP 桥
# 作用：node 进程在本机访问外网 HTTPS 会卡死（环境限制），但 Python 能正常出网。
# 因此 node 把请求参数经 stdin 传给本脚本，脚本用 urllib 发请求、流式返回 delta。
# 协议(行分隔 JSON 流)：每输出一行 JSON，其中 {"delta":"..."} 表示增量。
import sys, json, urllib.request

def chat(url, key, model, messages, temperature):
    body = json.dumps({"model": model, "messages": messages, "temperature": temperature, "stream": True}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key.strip(),
    })
    resp = urllib.request.urlopen(req, timeout=240)
    for raw in resp:
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            j = json.loads(payload)
            delta = ""
            ch = j.get("choices")
            if ch:
                delta = (ch[0].get("delta") or {}).get("content") or ""
            if delta:
                print(json.dumps({"delta": delta}, ensure_ascii=False), flush=True)
        except Exception:
            pass

def main():
    cfg = json.load(sys.stdin)
    url = cfg.get("url")
    key = cfg.get("key")
    model = cfg.get("model")
    messages = cfg.get("messages", [])
    temperature = cfg.get("temperature", 0.7)
    if not url:
        print(json.dumps({"error": "缺少 url"}, ensure_ascii=False), flush=True)
        return
    if not key:
        print(json.dumps({"error": "未配置 API Key，请在「设置」中填写"}, ensure_ascii=False), flush=True)
        return
    try:
        chat(url, key, model, messages, temperature)
        print(json.dumps({"done": True}), flush=True)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        print(json.dumps({"error": f"API 错误 {e.code}: {detail}"}, ensure_ascii=False), flush=True)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
