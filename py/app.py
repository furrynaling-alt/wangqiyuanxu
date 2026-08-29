# app.py — 往栖缘叙 · 数字生命工坊 主程序（pywebview 原生窗口）
# 功能：
#  - 后台起 Python HTTP 服务（端口 10086）
#  - pywebview 原生窗口加载 http://127.0.0.1:10086（无浏览器边框）
#  - 记住上次窗口位置/大小（存 data/window.json），下次自动恢复
#  - 原生窗口天然支持多屏拖动；拖动关闭时记住最终位置
# 启动: python app.py   （打包后由 PyInstaller 生成 exe）
import os
import sys
import json
import threading

# 把脚本目录加入 sys.path（import server 用）
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
# 注入 vendor（pywebview 实际代码在 py/vendor 下的 webview 包）
VENDOR = os.path.join(BASE, 'vendor')
if os.path.isdir(VENDOR):
    sys.path.insert(0, VENDOR)

# 项目根 / 数据目录
def app_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
ROOT = app_root()
DATA_DIR = os.path.join(ROOT, 'data')
WINDOW_JSON = os.path.join(DATA_DIR, 'window.json')
os.makedirs(DATA_DIR, exist_ok=True)

import webview
import server  # 本地后端（HTTP，端口 10086）

# 默认窗口：大尺寸 4:3 比例
DEFAULT_W = 1280
DEFAULT_H = 960
MIN_W = 1100
MIN_H = 780

def load_window_state():
    try:
        with open(WINDOW_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_window_state(w):
    try:
        # 读取多屏里窗口的位置
        x = getattr(w, 'x', None)
        y = getattr(w, 'y', None)
        state = {}
        if x is not None:
            state['x'] = int(x)
        if y is not None:
            state['y'] = int(y)
        state['width'] = int(getattr(w, 'width', DEFAULT_W))
        state['height'] = int(getattr(w, 'height', DEFAULT_H))
        with open(WINDOW_JSON, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def start_server():
    # HTTP 服务在后台线程跑；端口 10086
    t = threading.Thread(target=server.run, kwargs={'host': '127.0.0.1', 'port': 10086}, daemon=True)
    t.start()
    return t

def on_closed(window):
    save_window_state(window)

def main():
    start_server()
    # 首次可能服务没就绪，稍等
    import time
    time.sleep(0.8)
    wstate = load_window_state()
    x = wstate.get('x')
    y = wstate.get('y')
    width = wstate.get('width', DEFAULT_W)
    height = wstate.get('height', DEFAULT_H)

    window = webview.create_window(
        title='往栖缘叙 · 数字生命工坊',
        url='http://127.0.0.1:10086',
        width=width,
        height=height,
        x=x,
        y=y,
        resizable=True,
        confirm_close=False,
        background_color='#f5f6fb',
        text_select=False,
        min_size=(MIN_W, MIN_H),
    )
    # 若记忆的尺寸过小，强制扩到默认
    if width < MIN_W or height < MIN_H:
        try:
            window.resize(DEFAULT_W, DEFAULT_H)
        except Exception:
            pass
    window.events.closed += lambda: save_window_state(window)
    webview.start(debug=False)

if __name__ == '__main__':
    main()
