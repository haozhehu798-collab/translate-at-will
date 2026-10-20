# -*- coding: utf-8 -*-
"""
快捷翻译（Windows）
  Ctrl+Alt+E  翻译当前选中的文字（任意界面）
  Ctrl+Alt+S  框选屏幕区域，OCR 识别后翻译
  Ctrl+Alt+A  AI 提问（对话小窗，支持详细解释/翻译讲解/润色与追问）
后台驻留于系统托盘；提供图形“设置”界面；配置 config.ini 与程序同目录。
"""
import asyncio
import configparser
import csv
import ctypes
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.ttk as ttk
import urllib.parse
import winreg
from concurrent.futures import ThreadPoolExecutor
from tkinter import font as tkfont


def _setup_dpi():
    """在创建任何窗口前固定 DPI 感知，保证高分屏下清晰且尺寸一致。"""
    u = ctypes.windll.user32
    try:
        u.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        ctypes.windll.shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except Exception:
        pass
    try:
        u.SetProcessDPIAware()
    except Exception:
        pass


_setup_dpi()

import keyboard
import mss
import pystray
import requests
import win32api
import win32clipboard
import win32con
from PIL import Image, ImageDraw, ImageTk
from pystray import Menu, MenuItem as Item

try:
    import winocr
except Exception:
    winocr = None


# ---------------------------------------------------------------- 路径

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    # 源码运行时 fanyi.py 位于 <项目根>/src/，配置、历史与缓存统一放项目根，
    # 与打包后 exe 同目录放 config.ini 的行为保持一致。
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(APP_DIR, "config.ini")
HISTORY_PATH = os.path.join(APP_DIR, "history.csv")
CACHE_DIR = os.path.join(APP_DIR, "cache")


def resource_path(name):
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


ICON_PATH = resource_path("app.ico")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"}


# ---------------------------------------------------------------- 配置

DEFAULT_CONFIG = """\
# ===== 快捷翻译 配置文件 =====
# 一般无需手动编辑：右键托盘图标 ->“打开设置”，在图形界面修改即可。

[settings]
# 三个快捷键
hotkey_translate = ctrl+alt+e
hotkey_ocr = ctrl+alt+s
hotkey_ai = ctrl+alt+a
# 百度翻译官方 API（留空使用免费接口；申请方法见使用说明）
baidu_appid =
baidu_key =
# AI 助手（OpenAI 兼容）：deepseek / doubao / openai / custom
ai_preset = custom
ai_base_url =
ai_key =
ai_model =
# 专业领域（可选，会提示 AI 优先结合该领域）
ai_domain =
# 开关
auto_copy = true
auto_startup = true
history = true
# 发音偏好：us = 美音，uk = 英音
voice = us
# OCR 首选语言：en / zh-Hans-CN
ocr_lang = en
"""

DEFAULTS = {
    "hotkey_translate": "ctrl+alt+e",
    "hotkey_ocr": "ctrl+alt+s",
    "hotkey_ai": "ctrl+alt+a",
    "baidu_appid": "",
    "baidu_key": "",
    "ai_preset": "custom",
    "ai_base_url": "",
    "ai_key": "",
    "ai_model": "",
    "ai_domain": "",
    "auto_copy": True,
    "auto_startup": True,
    "history": True,
    "voice": "us",
    "ocr_lang": "en",
}

# AI 服务商预设：(base_url, 默认模型)
AI_PRESETS = [
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("豆包(火山方舟)", "https://ark.cn-beijing.volces.com/api/v3", ""),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("自定义", "", ""),
]

# 各服务商的常用模型（下拉可选，也可手动填写）；带推理的模型响应较慢
PRESET_MODELS = {
    "DeepSeek": ["deepseek-chat", "deepseek-flash", "deepseek-reasoner"],
    "豆包(火山方舟)": [],
    "OpenAI": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    "自定义": [],
}


class Config:
    def __init__(self, path):
        self.path = path
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_CONFIG)
        cp = configparser.ConfigParser()
        cp.read(self.path, encoding="utf-8")
        s = cp["settings"] if cp.has_section("settings") else {}

        def b(key):
            try:
                return s.getboolean(key, fallback=DEFAULTS[key])
            except Exception:
                return DEFAULTS[key]

        for key in ("hotkey_translate", "hotkey_ocr", "hotkey_ai",
                    "baidu_appid", "baidu_key", "ai_preset", "ai_base_url",
                    "ai_key", "ai_model", "ai_domain", "voice", "ocr_lang"):
            setattr(self, key, s.get(key, DEFAULTS[key]).strip()
                    if hasattr(s, "get") else DEFAULTS[key])
        self.auto_copy = b("auto_copy")
        self.auto_startup = b("auto_startup")
        self.history = b("history")

    def save(self):
        cp = configparser.ConfigParser()
        cp["settings"] = {
            "hotkey_translate": self.hotkey_translate,
            "hotkey_ocr": self.hotkey_ocr,
            "hotkey_ai": self.hotkey_ai,
            "baidu_appid": self.baidu_appid,
            "baidu_key": self.baidu_key,
            "ai_preset": self.ai_preset,
            "ai_base_url": self.ai_base_url,
            "ai_key": self.ai_key,
            "ai_model": self.ai_model,
            "ai_domain": self.ai_domain,
            "auto_copy": "true" if self.auto_copy else "false",
            "auto_startup": "true" if self.auto_startup else "false",
            "history": "true" if self.history else "false",
            "voice": self.voice,
            "ocr_lang": self.ocr_lang,
        }
        with open(self.path, "w", encoding="utf-8") as f:
            cp.write(f)

    def snapshot(self):
        return dict((k, getattr(self, k)) for k in DEFAULTS)


# ---------------------------------------------------------------- 开机自启

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VAL_NAME = "DoubaoFanyi"


def set_autostart(enable):
    try:
        if enable:
            if getattr(sys, "frozen", False):
                target = '"%s"' % sys.executable
            else:
                target = '"%s" "%s"' % (sys.executable,
                                        os.path.abspath(__file__))
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.SetValueEx(k, VAL_NAME, 0, winreg.REG_SZ, target)
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, VAL_NAME)
            except FileNotFoundError:
                pass
    except Exception:
        pass


def is_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VAL_NAME)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 历史

def append_history(src, dst):
    if not os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(["时间", "原文", "译文"])
    try:
        with open(HISTORY_PATH, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"),
                        src.replace("\n", " ").strip(),
                        dst.replace("\n", " ").strip()])
        if os.path.getsize(HISTORY_PATH) > 2 * 1024 * 1024:
            with open(HISTORY_PATH, "r", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
            head, body = rows[:1], rows[1:]
            body = body[-1500:]
            with open(HISTORY_PATH, "w", encoding="utf-8-sig",
                      newline="") as f:
                csv.writer(f).writerows(head + body)
    except Exception:
        pass


# ---------------------------------------------------------------- 剪贴板

def _open_clipboard(retries=5):
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(0.02)
    return False


def clipboard_get_text():
    if not _open_clipboard():
        return None
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
    except Exception:
        return None
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
    return None


def clipboard_get_dib():
    if not _open_clipboard():
        return None
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
            return win32clipboard.GetClipboardData(win32con.CF_DIB)
    except Exception:
        return None
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
    return None


def clipboard_set_text(text):
    if not _open_clipboard():
        return
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    except Exception:
        pass
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass


def clipboard_restore(text, dib):
    if not _open_clipboard():
        return
    try:
        win32clipboard.EmptyClipboard()
        if dib is not None:
            win32clipboard.SetClipboardData(win32con.CF_DIB, dib)
        if text is not None:
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    except Exception:
        pass
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass


def clean_text(s):
    return s.strip().replace("\r\n", "\n").replace("\r", "\n")


def grab_selected():
    """模拟 Ctrl+C 获取选中文字，结束后还原剪贴板。"""
    old_text = clipboard_get_text()
    old_dib = clipboard_get_dib()
    try:
        keyboard.send("ctrl+c")
    except Exception:
        return None
    deadline = time.time() + 1.0
    new = None
    while time.time() < deadline:
        time.sleep(0.04)
        t = clipboard_get_text()
        if t and t.strip() and t != old_text:
            new = t
            break
    clipboard_restore(old_text, old_dib)
    if not new:
        return None
    return clean_text(new)


# ---------------------------------------------------------------- 语言判断

def has_chinese(s):
    return any("一" <= ch <= "\u9fff" for ch in s)


def is_abbr(q):
    """全大写缩写，如 TEC / PSO / XGBOOST。"""
    q = q.strip()
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", q))


def is_word_like(q):
    """是否为单词/简单短语（决定是否显示音标、走词典聚合）。"""
    q = q.strip()
    if is_abbr(q):
        return True
    if has_chinese(q) or len(q) > 30:
        return False
    words = q.split()
    if not (1 <= len(words) <= 2):
        return False
    return all(re.fullmatch(r"[A-Za-z][A-Za-z''\-]*", w) for w in words)


# ---------------------------------------------------------------- 有道（多字段聚合）

def _join_li(li):
    if isinstance(li, list):
        out = ""
        for x in li:
            if isinstance(x, dict):
                out += x.get("i") or x.get("text") or ""
            else:
                out += str(x)
        return out
    return li if isinstance(li, str) else None


def youdao_lookup(q):
    """聚合有道 jsonapi：音标 / ec / special(学科专业) / web_trans / wiki。"""
    r = requests.get("https://dict.youdao.com/jsonapi", params={"q": q},
                     headers=UA, timeout=8)
    r.raise_for_status()
    r.encoding = "utf-8"
    d = r.json()
    res = {"uk": None, "us": None, "ec": [], "special": [],
           "web": [], "wiki": None}

    simple = (d.get("simple") or {}).get("word")
    if simple:
        res["uk"] = simple[0].get("ukphone")
        res["us"] = simple[0].get("usphone")

    ec = (d.get("ec") or {}).get("word")
    if ec:
        w0 = ec[0]
        res["uk"] = res["uk"] or w0.get("ukphone")
        res["us"] = res["us"] or w0.get("usphone")
        for trs in w0.get("trs", []):
            for tr in trs.get("tr", []):
                l = tr.get("l") or {}
                text = _join_li(l.get("i"))
                pos = l.get("pos")
                if text:
                    if pos and not text.startswith(pos):
                        text = "%s %s" % (pos, text)
                    res["ec"].append(text)

    # special：按学科的专业释义（论文库）
    sp = d.get("special") or {}
    for entry in sp.get("entries", []):
        e = entry.get("entry") or {}
        major = e.get("major") or "专业释义"
        for trs in e.get("trs", []):
            t = trs.get("tr")
            if isinstance(t, dict):
                text = t.get("nat") or t.get("text") or t.get("name")
            else:
                text = t
            if text:
                res["special"].append(
                    ("【%s】%s" % (major, text)))

    # web_trans：精确匹配项的全部网络释义
    wt = (d.get("web_trans") or {}).get("web-translation")
    if wt:
        qlow = q.strip().lower()
        for item in wt:
            key = (item.get("key") or "").strip().lower()
            if key == qlow:
                for t in item.get("trans", []):
                    v = t.get("value")
                    if v and v not in res["web"]:
                        res["web"].append(v)
                break

    # wikipedia_digest（结构随版本，防御性提取）
    wd = d.get("wikipedia_digest")
    if isinstance(wd, dict):
        cand = (wd.get("summary") or wd.get("digest")
                or wd.get("wikipedia-digest"))
        if isinstance(cand, dict):
            res["wiki"] = cand.get("text") or cand.get("value")
        elif isinstance(cand, str):
            res["wiki"] = cand
        elif isinstance(cand, list) and cand:
            c0 = cand[0]
            if isinstance(c0, dict):
                s0 = c0.get("summary") or c0
                res["wiki"] = s0.get("text") if isinstance(s0, dict) else s0
    return res


# ---------------------------------------------------------------- 百度 sug

def baidu_sug(q):
    r = requests.post("https://fanyi.baidu.com/sug", data={"kw": q},
                      headers=UA, timeout=8)
    r.raise_for_status()
    r.encoding = "utf-8"
    out = []
    for it in (r.json().get("data") or []):
        k = (it.get("k") or "").strip()
        v = it.get("v") or ""
        out.append(("%s  %s" % (k, v)).strip())
    return out


# ---------------------------------------------------------------- MyMemory

def mymemory_translate(q):
    is_zh = has_chinese(q)
    frm = "zh-CN" if is_zh else "en-GB"
    to = "en-GB" if is_zh else "zh-CN"
    r = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": q, "langpair": "%s|%s" % (frm, to),
                "de": "fanyi-tool@example.com"},
        headers=UA, timeout=11,
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    d = r.json()
    status = d.get("responseStatus")
    if status != 200:
        raise RuntimeError("MyMemory 错误 %s：%s"
                           % (status, d.get("responseDetails")))
    text = (d.get("responseData") or {}).get("translatedText")
    if not text:
        raise RuntimeError("MyMemory 未返回结果")
    return text


# ---------------------------------------------------------------- 百度官方

def baidu_translate(q, appid, key):
    frm, to = ("zh", "en") if has_chinese(q) else ("en", "zh")
    salt = str(int(time.time() * 1000))
    sign = hashlib.md5((appid + q + salt + key).encode("utf-8")).hexdigest()
    r = requests.get(
        "https://fanyi-api.baidu.com/api/trans/vip/translate",
        params={"q": q, "from": frm, "to": to, "appid": appid,
                "salt": salt, "sign": sign},
        headers=UA, timeout=9,
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    d = r.json()
    if "trans_result" not in d:
        raise RuntimeError("百度接口错误 %s：%s"
                           % (d.get("error_code"), d.get("error_msg")))
    return "\n".join(x["dst"] for x in d["trans_result"])


def baidu_dict(q, appid, key):
    salt = str(int(time.time() * 1000))
    sign = hashlib.md5((appid + q + salt + key).encode("utf-8")).hexdigest()
    r = requests.get(
        "https://fanyi-api.baidu.com/api/trans/vip/dict",
        params={"q": q, "from": "en", "to": "zh", "appid": appid,
                "salt": salt, "sign": sign},
        headers=UA, timeout=6,
    )
    r.encoding = "utf-8"
    d = r.json()
    sym = d["dict_result"]["simple_means"]["symbols"][0]
    return (sym.get("ph_en") or None), (sym.get("ph_am") or None)


# ---------------------------------------------------------------- 单词聚合

def collect_word(q, cfg):
    """返回 (groups, uk, us)；groups 为多来源分组列表。"""
    y = None
    try:
        y = youdao_lookup(q)
    except Exception:
        y = None
    uk = us = None
    if y:
        uk, us = y["uk"], y["us"]

    sug = []
    try:
        sug = baidu_sug(q)
    except Exception:
        sug = []

    official = None
    if cfg.baidu_appid and cfg.baidu_key:
        try:
            official = baidu_translate(q, cfg.baidu_appid, cfg.baidu_key)
        except Exception:
            official = None
        if not (uk or us):
            try:
                uk, us = baidu_dict(q.lower(), cfg.baidu_appid, cfg.baidu_key)
            except Exception:
                pass

    groups = []
    if y and y["special"]:
        groups.append({"title": "专业释义 · 来源于论文库",
                       "items": y["special"]})
    if y and y["ec"]:
        groups.append({"title": "词典释义（含缩写全称）",
                       "items": y["ec"]})
    if y and y["web"]:
        groups.append({"title": "网络释义", "items": y["web"]})
    if y and y["wiki"]:
        groups.append({"title": "百科", "items": [y["wiki"]]})
    if official:
        groups.append({"title": "百度翻译（官方）", "items": [official]})
    if sug:
        groups.append({"title": "百度词典", "items": sug})
    return groups, uk, us


def translate_sentence(q, cfg):
    """长句翻译，返回 (译文, 引擎)。"""
    if cfg.baidu_appid and cfg.baidu_key:
        try:
            return baidu_translate(q, cfg.baidu_appid, cfg.baidu_key), "百度翻译"
        except Exception:
            pass
    return mymemory_translate(q), "MyMemory"


def _count_lines(text):
    return len([l for l in text.replace("\r\n", "\n").split("\n") if l.strip()])


def translate_block(text, cfg, on_progress=None):
    """多行文本逐行翻译，保持行序一一对应。

    返回 (pairs, engine)；pairs 为 [(原文行, 译文行), ...]，
    原文中的空行保留为 ("", "")，用于还原段落间隔。
    on_progress(done, total) 为可选的进度回调（逐行完成时调用）。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    idx = [i for i, l in enumerate(lines) if l.strip()]
    results = {}
    use_baidu = bool(cfg.baidu_appid and cfg.baidu_key)
    engine = "百度翻译" if use_baidu else "MyMemory"

    # 百度官方接口支持整段按 \n 分段返回，一次请求即可逐行对应
    if use_baidu:
        try:
            joined = "\n".join(lines[i].strip() for i in idx)
            full = baidu_translate(joined, cfg.baidu_appid, cfg.baidu_key)
            dlines = [x.strip() for x in full.split("\n")]
            if len(dlines) == len(idx):
                for k, i in enumerate(idx):
                    results[i] = dlines[k]
        except Exception:
            results = {}

    # 未配置百度 / 整段失败或行数不匹配 → 逐行翻译（MyMemory 并发）
    missing = [i for i in idx if i not in results]

    def work(i):
        try:
            dst, _eng = translate_sentence(lines[i].strip(), cfg)
            return i, (dst or "").strip()
        except Exception:
            return i, ""

    if missing:
        total = len(missing)
        done = [0]
        lock = threading.Lock()

        def report():
            if on_progress:
                try:
                    on_progress(done[0], total)
                except Exception:
                    pass

        if use_baidu:
            # 百度标准版 QPS=1，串行并轻微限速
            for i in missing:
                _i, d = work(i)
                results[_i] = d
                with lock:
                    done[0] += 1
                report()
                time.sleep(0.2)
        else:
            # 免费接口并发提速，最多 6 路
            def work2(i):
                r = work(i)
                with lock:
                    done[0] += 1
                report()
                return r

            with ThreadPoolExecutor(
                    max_workers=min(6, total)) as ex:
                for i, d in ex.map(work2, missing):
                    results[i] = d

    pairs = []
    for i in range(len(lines)):
        if i in results:
            pairs.append((lines[i].strip(), results[i]))
        else:
            pairs.append(("", ""))
    return pairs, engine


# ---------------------------------------------------------------- 发音

_voice_lock = threading.Lock()


def play_mp3(path):
    winmm = ctypes.windll.winmm
    with _voice_lock:
        winmm.mciSendStringW("close fyvoice", None, 0, None)
        winmm.mciSendStringW(
            'open "%s" type mpegvideo alias fyvoice' % path, None, 0, None
        )
        winmm.mciSendStringW("play fyvoice", None, 0, None)

        def close_later():
            time.sleep(7)
            winmm.mciSendStringW("close fyvoice", None, 0, None)

        threading.Thread(target=close_later, daemon=True).start()


def speak(text, accent="us"):
    def task():
        try:
            vtype = 0 if accent == "uk" else 1
            url = ("https://dict.youdao.com/dictvoice?type=%d&audio=%s"
                   % (vtype, urllib.parse.quote(text)))
            r = requests.get(url, headers=UA, timeout=8)
            r.raise_for_status()
            os.makedirs(CACHE_DIR, exist_ok=True)
            mp3 = os.path.join(CACHE_DIR, "voice.mp3")
            with open(mp3, "wb") as f:
                f.write(r.content)
            play_mp3(mp3)
        except Exception:
            pass

    threading.Thread(target=task, daemon=True).start()


# ---------------------------------------------------------------- OCR

class OcrLangError(Exception):
    pass


def virtual_screen():
    u32 = ctypes.windll.user32
    return (u32.GetSystemMetrics(76), u32.GetSystemMetrics(77),
            u32.GetSystemMetrics(78), u32.GetSystemMetrics(79))


def capture_virtual():
    with mss.mss() as sct:
        mon = sct.monitors[0]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    return img, dict(mon)


def ocr_available_langs():
    try:
        from winrt.windows.media.ocr import OcrEngine
        return [l.language_tag for l in
                OcrEngine.available_recognizer_languages]
    except Exception:
        return []


def ocr_recognize(img, lang_pref="en"):
    """返回 (识别文本, 兜底语言tag或None)。"""
    if winocr is None:
        raise RuntimeError("OCR 组件加载失败，请重新获取程序。")
    langs = ocr_available_langs()
    tag = None
    for t in langs:
        if t.lower().startswith(lang_pref.lower()):
            tag = t
            break
    fallback_tag = None
    if tag is None:
        for t in langs:
            if t.lower().startswith("zh"):
                fallback_tag = t
                break
        if fallback_tag:
            tag = fallback_tag
        elif langs:
            tag = langs[0]
        else:
            raise OcrLangError(
                "系统未安装任何 OCR 语言包。\n\n"
                "安装方法：打开“Windows 设置 → 时间和语言 → 语言和区域”，\n"
                "添加语言“English (英语)”，并勾选“光学字符识别”。\n\n"
                "现在将为你打开该设置页。"
            )

    async def run():
        return await winocr.recognize_pil(img, tag)

    result = asyncio.run(run())
    # 注意：result.text 会把多行用空格拼接成一行（丢失换行），导致多行内容无法
    # 逐行对照。这里直接从 result.lines 逐行还原，用 \n 连接。
    try:
        text = "\n".join((ln.text or "").strip()
                         for ln in result.lines if (ln.text or "").strip())
    except Exception:
        text = result.text
    return text, fallback_tag


def _enlarge_for_ocr(img):
    """对截图选区等比放大，显著提升“图片内小字 / 彩色 / 压缩字”的识别率。"""
    try:
        img = img.convert("RGB")
        w, h = img.size
        longest = max(w, h)
        if longest < 1000:
            factor = 2.0
        elif longest < 1600:
            factor = 1.5
        else:
            factor = 1.0
        if factor > 1.0:
            img = img.resize(
                (max(1, int(w * factor)), max(1, int(h * factor))),
                Image.LANCZOS)
        return img
    except Exception:
        return img


# ---------------------------------------------------------------- RegionSelector

class RegionSelector(tk.Toplevel):
    """全屏冻结快照 + 鼠标拖拽框选（同微信截图，可保留弹出菜单）。

    防卡死设计：
      - 压暗层为固定全屏点阵（拖拽时不重绘），框内“清晰区”只贴一块与背景同源
        的小裁剪图，并节流到约 55 帧/秒更新，拖拽跟手、不阻塞主线程；
      - Esc / 右键取消，且通过全局键盘钩子兜底（焦点不在遮罩上也能取消）；
      - 30 秒未操作自动取消；任何异常都保证遮罩被销毁，绝不留下全屏黑窗；
      - 框选坐标按 canvas 与截图的实际尺寸比例换算，高 DPI 下也不会错位。
    """

    CANCEL_AFTER_MS = 30000

    def __init__(self, master, vleft, vtop, vw, vh, on_done, background=None):
        super().__init__(master)
        self.on_done = on_done
        self.bg_img = background
        self.vleft, self.vtop = vleft, vtop
        self.vw, self.vh = vw, vh
        self.sx = self.sy = None
        self.rect = None
        self.size_lbl = None
        self.tip_lbl = None
        self._finished = False
        self._esc_hook = None
        self._timeout_id = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="black")
        self.geometry("%dx%d+%d+%d" % (vw, vh, vleft, vtop))
        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0,
                                width=vw, height=vh, cursor="crosshair",
                                bd=0, takefocus=1)
        self.canvas.pack(fill="both", expand=True)

        # 背景冻结快照（一次性生成；失败则退化为纯黑遮罩，仍可框选）
        self.photo = None
        if background is not None:
            try:
                self.photo = ImageTk.PhotoImage(background)
                self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
            except Exception:
                self.photo = None

        # 压暗层：一块固定全屏的半透明点阵。创建后坐标永不再变，因此框选拖拽时
        # 这一层完全不参与重绘——逐帧重绘大面积 stipple 正是之前卡顿的主要原因。
        self.m_dim = self.canvas.create_rectangle(
            0, 0, vw, vh, fill="black", stipple="gray25", outline="")

        # 框内清晰快照：拖拽时把背景图“框选区域”的裁剪图贴到这一层（盖在压暗层
        # 之上），形成“框外压暗、框内清晰”的效果。该层只在节流回调里更新，且是
        # 小图上传，不会像整屏重绘那样掉帧。
        self._hole_photo = None
        self._hole_pending = False
        self._last_box = None
        self.hole_img = self.canvas.create_image(0, 0, anchor="nw")

        self.rect = self.canvas.create_rectangle(
            0, 0, 0, 0, outline="#3B82F6", width=2)
        self.size_lbl = self.canvas.create_text(
            8, 8, anchor="sw", text="", fill="white",
            font=(FONT_FAMILY, 9))
        self.tip_lbl = self.canvas.create_text(
            vw // 2, 46,
            text="拖动鼠标框选要翻译的区域        Esc / 右键 取消",
            fill="white", font=(FONT_FAMILY, 12, "bold"))

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-3>", self.on_cancel)
        self.canvas.bind("<Escape>", self.on_cancel)
        self.bind("<Escape>", self.on_cancel)

        self.after(60, self._arm)
        self._timeout_id = self.after(self.CANCEL_AFTER_MS, self.on_cancel)
        # 全局 Esc 兜底：即使焦点不在遮罩上，也能强制取消（不拦截按键）
        try:
            self._esc_hook = keyboard.add_hotkey(
                "esc", lambda: self.after(0, self.on_cancel), suppress=False)
        except Exception:
            self._esc_hook = None

    def _arm(self):
        if self._finished:
            return
        try:
            self.focus_force()
            self.canvas.focus_set()
        except Exception:
            pass

    def on_press(self, e):
        self.sx, self.sy = e.x, e.y
        self._last_box = None
        if self.tip_lbl is not None:
            self.canvas.delete(self.tip_lbl)
            self.tip_lbl = None
        self.canvas.coords(self.rect, e.x, e.y, e.x, e.y)
        self.canvas.coords(self.size_lbl, e.x + 8, e.y - 10)
        self._set_hole(e.x, e.y, e.x, e.y)

    def _clamp_box(self, x1, y1, x2, y2):
        x1 = max(0, min(self.vw, x1))
        x2 = max(0, min(self.vw, x2))
        y1 = max(0, min(self.vh, y1))
        y2 = max(0, min(self.vh, y2))
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        return int(x1), int(y1), int(x2), int(y2)

    def _set_hole(self, x1, y1, x2, y2):
        """把背景图的框选区域作为清晰小图贴到压暗层之上，形成“挖洞”效果。"""
        if x2 - x1 < 2 or y2 - y1 < 2 or self.bg_img is None:
            self._hole_photo = None
            try:
                self.canvas.itemconfig(self.hole_img, image="")
            except Exception:
                pass
            return
        try:
            # 背景全屏图与 canvas 同尺寸（同源 mss 截图），裁剪坐标可直接对应
            crop = self.bg_img.crop((x1, y1, x2, y2))
            self._hole_photo = ImageTk.PhotoImage(crop)
            self.canvas.itemconfig(self.hole_img, image=self._hole_photo)
            self.canvas.coords(self.hole_img, x1, y1)
        except Exception:
            self._hole_photo = None

    def _flush_hole(self):
        self._hole_pending = False
        if self._finished or self._last_box is None:
            return
        self._set_hole(*self._last_box)

    def on_drag(self, e):
        if self.sx is None:
            return
        x1, y1, x2, y2 = self._clamp_box(
            min(self.sx, e.x), min(self.sy, e.y),
            max(self.sx, e.x), max(self.sy, e.y))
        # 边框与尺寸标签是轻量矢量图元，立即更新，保证跟手
        self.canvas.coords(self.rect, x1, y1, x2, y2)
        self.canvas.coords(self.size_lbl, x2 + 8, y1 - 10)
        self.canvas.itemconfigure(self.size_lbl,
                                  text="%d × %d" % (x2 - x1, y2 - y1))
        # 清晰小图（像素上传）相对重，节流到约 55 帧/秒，避免逐帧重建造成卡顿
        self._last_box = (x1, y1, x2, y2)
        if not self._hole_pending:
            self._hole_pending = True
            self.after(18, self._flush_hole)

    def on_release(self, e):
        if self.sx is None:
            self.on_cancel()
            return
        x1, y1 = min(self.sx, e.x), min(self.sy, e.y)
        x2, y2 = max(self.sx, e.x), max(self.sy, e.y)
        if x2 - x1 < 5 or y2 - y1 < 5:
            self.on_cancel()
            return
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(self.vw, x2), min(self.vh, y2)
        bbox = self._to_physical(x1, y1, x2, y2)
        self._safe_finish(bbox)

    def _to_physical(self, x1, y1, x2, y2):
        """canvas 显示坐标 -> 背景截图像素坐标（按实际尺寸比例换算，DPI 无关）。"""
        try:
            cw = self.canvas.winfo_width() or self.vw
            ch = self.canvas.winfo_height() or self.vh
            if self.bg_img is not None:
                iw, ih = self.bg_img.size
                sx, sy = iw / cw, ih / ch
            else:
                sx = sy = 1.0
        except Exception:
            sx = sy = 1.0
        return (int(round(x1 * sx)) + self.vleft,
                int(round(y1 * sy)) + self.vtop,
                int(round(x2 * sx)) + self.vleft,
                int(round(y2 * sy)) + self.vtop)

    def on_cancel(self, *_):
        self._safe_finish(None)

    def _safe_finish(self, bbox):
        """无论正常、异常、超时、取消，都保证遮罩只销毁一次、回调只执行一次。"""
        if self._finished:
            return
        self._finished = True
        if self._timeout_id is not None:
            try:
                self.after_cancel(self._timeout_id)
            except Exception:
                pass
            self._timeout_id = None
        if self._esc_hook is not None:
            try:
                keyboard.remove_hotkey(self._esc_hook)
            except Exception:
                pass
            self._esc_hook = None
        try:
            self.withdraw()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        try:
            self.on_done(bbox)
        except Exception:
            pass


# ---------------------------------------------------------------- 样式

C = {
    "bg": "#FFFFFF",
    "src": "#1F2937",
    "dst": "#102033",
    "sub": "#7A8699",
    "accent": "#2B6CB0",
    "line": "#E7EAF0",
    "tag": "#F1F5F9",
}
FONT_FAMILY = "Microsoft YaHei UI"


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


def force_foreground(hwnd):
    u32 = ctypes.windll.user32
    if u32.GetForegroundWindow() == hwnd:
        return
    cur = ctypes.windll.kernel32.GetCurrentThreadId()
    fg = u32.GetForegroundWindow()
    fg_tid = u32.GetWindowThreadProcessId(fg, None)
    try:
        u32.AttachThreadInput(cur, fg_tid, True)
        u32.SetForegroundWindow(hwnd)
        u32.BringWindowToTop(hwnd)
    except Exception:
        pass
    finally:
        try:
            u32.AttachThreadInput(cur, fg_tid, False)
        except Exception:
            pass


def workarea_at(x, y):
    u32 = ctypes.windll.user32
    hmon = u32.MonitorFromPoint(_POINT(x, y), 2)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    u32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    return mi.rcWork


def make_text_widget(parent, text, size, color, bold=False,
                     width_chars=46, max_lines=4):
    f = tkfont.Font(family=FONT_FAMILY, size=size,
                    weight="bold" if bold else "normal")
    t = tk.Text(parent, wrap="word", relief="flat", bg=C["bg"], bd=0,
                font=f, height=1, width=width_chars, padx=0, pady=0,
                spacing1=0, spacing3=2, foreground=color,
                highlightthickness=0, cursor="arrow",
                selectbackground="#C7DEFE", selectforeground=C["dst"])
    t.insert("1.0", text)
    t.configure(state="disabled")

    def fit():
        t.update_idletasks()
        res = t.count("1.0", "end", "displaylines")
        lines = int(res[0]) if res else 1
        t.configure(height=max(min(lines, max_lines), 1))

    t.after(20, fit)
    return t


def pretty_hotkey(combo):
    """把内部快捷键写法转成友好显示：f1 -> F1，ctrl+alt+e -> Ctrl+Alt+E"""
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    out = []
    for p in combo.replace(" ", "").split("+"):
        pl = p.lower()
        if pl in names:
            out.append(names[pl])
        elif len(pl) > 1 and pl[0] == "f" and pl[1:].isdigit():
            out.append("F" + pl[1:])
        elif len(pl) == 1:
            out.append(pl.upper())
        else:
            out.append(p.capitalize())
    return "+".join(out)


def enable_drag(win, widgets):
    """按住 widgets 区域即可拖动无边框窗口 win。"""
    state = {"x": 0, "y": 0}

    def start(e):
        state["x"] = e.x_root - win.winfo_x()
        state["y"] = e.y_root - win.winfo_y()

    def move(e):
        try:
            win.geometry("+%d+%d" % (e.x_root - state["x"],
                                     e.y_root - state["y"]))
        except Exception:
            pass

    for w in widgets:
        try:
            w.configure(cursor="fleur")
        except Exception:
            pass
        w.bind("<Button-1>", start)
        w.bind("<B1-Motion>", move)


def bind_escape(win, callback, widgets=None):
    """顶层 + 各可聚焦子控件都绑定 ESC，确保无边框窗口也能按 ESC 关闭。"""
    def handler(e):
        callback()
        return "break"
    win.bind("<Escape>", handler)
    for w in (widgets or []):
        w.bind("<Escape>", handler)


# ---------------------------------------------------------------- ResultWindow

class ResultWindow(tk.Toplevel):
    WIDTH = 400

    def __init__(self, master, data, cfg, app=None):
        super().__init__(master)
        self.data = data
        self.cfg = cfg
        self.app = app
        self.refine_q = queue.Queue()
        self.refine_btn = None
        self.engine_lbl = None
        self.attributes("-topmost", True)
        _t = data["src"]
        self.title(_t if len(_t) <= 40 else _t[:40] + "…")
        self.configure(bg=C["bg"])

        outer = tk.Frame(self, bg=C["bg"])
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=C["bg"])
        inner.pack(fill="both", expand=True)
        body = tk.Frame(inner, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=15, pady=(12, 11))

        if data.get("uk") or data.get("us"):
            ph = tk.Frame(body, bg=C["bg"])
            ph.pack(fill="x", pady=(7, 0), anchor="w")
            if data.get("uk"):
                self._phonetic_chip(ph, "英", data["uk"], "uk")
            if data.get("us"):
                self._phonetic_chip(ph, "美", data["us"], "us")

        tk.Frame(body, bg=C["line"], height=1).pack(fill="x", pady=10)

        # 内容：word 模式多来源分组；sentence 模式单译文/多行对照
        cf = tk.Frame(body, bg=C["bg"])
        cf.pack(fill="both", expand=True)
        self.content = tk.Text(cf, wrap="word", relief="flat", bg=C["bg"], bd=0,
                               font=(FONT_FAMILY, 10), height=1, width=46,
                               padx=0, pady=0, highlightthickness=0,
                               cursor="arrow")
        self.sb = tk.Scrollbar(cf, orient="vertical",
                               command=self.content.yview)
        self.content.configure(yscrollcommand=self.sb.set)
        self.content.tag_config("gtitle", foreground=C["accent"],
                                font=(FONT_FAMILY, 10, "bold"),
                                spacing1=8, spacing3=2)
        self.content.tag_config("gitem", foreground=C["dst"],
                                lmargin1=8, lmargin2=16, spacing1=1, spacing3=2)
        self.content.tag_config("main", foreground=C["dst"],
                                font=(FONT_FAMILY, 12))
        self.content.tag_config("srcline", foreground=C["sub"],
                                font=(FONT_FAMILY, 9), spacing1=8, spacing3=1)
        self.content.tag_config("note", foreground=C["sub"],
                                font=(FONT_FAMILY, 9), spacing1=6)
        self._fill_content()

        foot = tk.Frame(body, bg=C["bg"])
        foot.pack(fill="x", pady=(10, 0))
        tips = ["Esc 关闭"]
        if cfg.auto_copy:
            tips.append("译文已复制")
        if data.get("ocr_fallback"):
            tips.append("未装英文OCR包，兼容识别中")
        tk.Label(foot, text=" · ".join(tips), bg=C["bg"], fg=C["sub"],
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.engine_lbl = tk.Label(foot, text=data.get("engine", "多来源"),
                                   bg=C["tag"], fg=C["sub"],
                                   font=(FONT_FAMILY, 8), padx=7, pady=1)
        self.engine_lbl.pack(side="right")
        if app is not None and getattr(app, "ai_ready", lambda: False)():
            if data.get("mode") == "word":
                self.refine_btn = self._make_ai_btn(
                    foot, "AI 详解", self._on_ai_explain)
            else:
                self.refine_btn = self._make_ai_btn(
                    foot, "AI 精译", self._on_ai_refine)

        bind_escape(self, self.close, [self.content])
        self.after(40, self._finish)

    # ---- 内容渲染（AI 精译后可复用重绘） ----
    def _fill_content(self):
        content = self.content
        content.configure(state="normal")
        content.delete("1.0", "end")
        data = self.data
        if data.get("mode") == "word":
            for g in data["groups"]:
                content.insert("end", g["title"] + "\n", "gtitle")
                for it in g["items"]:
                    content.insert("end", "• " + it + "\n", "gitem")
        else:
            pairs = data.get("pairs")
            if pairs:
                # 多行：逐行对照（原文行在上、译文行在下），空行还原段落间隔
                for sline, dline in pairs:
                    if not sline and not dline:
                        content.insert("end", "\n")
                        continue
                    content.insert("end", sline + "\n", "srcline")
                    content.insert("end", dline + "\n\n", "main")
            else:
                content.insert("end", data.get("dst", ""), "main")
        content.configure(state="disabled")
        self.after(10, self._fit_content)

    def _fit_content(self):
        try:
            content = self.content
            content.update_idletasks()
            res = content.count("1.0", "end", "displaylines")
            lines = int(res[0]) if res else 1
            if lines > 15:
                content.configure(height=15)
                self.sb.pack(side="right", fill="y")
            else:
                content.configure(height=max(lines, 1))
            content.pack(side="left", fill="both", expand=True)
        except Exception:
            pass

    def _make_ai_btn(self, parent, text, cmd):
        btn = tk.Label(parent, text=text, bg=C["accent"], fg="white",
                       font=(FONT_FAMILY, 9, "bold"), padx=10, pady=2,
                       cursor="hand2")
        btn.pack(side="right", padx=(8, 0))
        btn.bind("<Button-1>", lambda e: cmd())
        return btn

    def _alive(self):
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    # ---- AI 详解（单词）：打开 AI 对话窗并自动解释 ----
    def _on_ai_explain(self):
        if self.app is None:
            return
        src = self.data.get("src", "")
        try:
            self.close()
        except Exception:
            pass
        try:
            self.app.open_ai(src)
        except Exception:
            pass

    # ---- AI 精译（长句/段落） ----
    def _on_ai_refine(self):
        if self.app is None or not self.app.ai_ready():
            return
        if self.refine_btn is not None:
            self.refine_btn.configure(text="精译中…")
            self.refine_btn.unbind("<Button-1>")
        self.content.configure(state="normal")
        self.content.insert("end", "\nAI 精译中，请稍候…\n", "note")
        self.content.configure(state="disabled")
        self._fit_content()
        threading.Thread(target=self._refine_worker, daemon=True).start()
        self.after(150, self._poll_refine)

    def _refine_worker(self):
        try:
            src = self.data["src"]
            if self.data.get("pairs"):
                n = len([1 for s, _d in self.data["pairs"] if s])
                sysmsg = ("你是专业翻译。下面共有 %d 行外文（每行一句，忽略其中的空行）。"
                          "请逐行翻译成简体中文，并且只输出 %d 行译文，"
                          "每一行译文严格对应原文的一行；不要输出空行、序号、"
                          "解释或原文，也不要合并或增减行数。" % (n, n))
            else:
                sysmsg = ("你是专业翻译。把下面的外文准确、通顺、符合中文表达习惯地"
                          "翻译成简体中文，专业术语请使用对应领域的规范译法。"
                          "只输出译文，不要解释、不要标注。")
            body = {"model": self.cfg.ai_model,
                    "messages": [{"role": "system", "content": sysmsg},
                                 {"role": "user", "content": src}],
                    "stream": False}
            r = requests.post(
                self.cfg.ai_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + self.cfg.ai_key,
                         "Content-Type": "application/json"},
                json=body, timeout=(10, 90))
            if r.status_code != 200:
                self.refine_q.put(("err", "HTTP %s %s"
                                  % (r.status_code, r.text[:150])))
                return
            out = r.json()["choices"][0]["message"]["content"].strip()
            self.refine_q.put(("ok", out))
        except Exception as e:
            self.refine_q.put(("err", str(e)))

    def _poll_refine(self):
        try:
            kind, payload = self.refine_q.get_nowait()
        except queue.Empty:
            if self._alive():
                self.after(150, self._poll_refine)
            return
        if not self._alive():
            return
        if kind == "err":
            if self.refine_btn is not None:
                self.refine_btn.configure(text="AI 精译")
                self.refine_btn.bind(
                    "<Button-1>", lambda e: self._on_ai_refine())
            self.content.configure(state="normal")
            self.content.insert("end", "AI 精译失败：%s\n" % payload, "note")
            self.content.configure(state="disabled")
            self._fit_content()
            return

        out = payload
        pairs = self.data.get("pairs")
        joined = out
        if pairs:
            dlines = [d.strip() for d in out.split("\n") if d.strip()]
            src_idx = [i for i, (s, _d) in enumerate(pairs) if s]
            if len(dlines) == len(src_idx):
                newpairs, di = [], 0
                for s, _d in pairs:
                    if s:
                        newpairs.append((s, dlines[di]))
                        di += 1
                    else:
                        newpairs.append(("", ""))
                self.data["pairs"] = newpairs
                joined = "\n".join(d for _, d in newpairs if d)
            else:
                # AI 未严格对齐行数：整段呈现，放弃逐行对照
                self.data["pairs"] = None
                self.data["dst"] = out
        else:
            self.data["dst"] = out
        self.data["engine"] = "AI 精译"
        if self.engine_lbl is not None:
            self.engine_lbl.configure(text="AI 精译")
        if self.refine_btn is not None:
            self.refine_btn.pack_forget()
        self._fill_content()
        try:
            if self.cfg.auto_copy:
                clipboard_set_text(joined)
            if self.cfg.history:
                append_history(self.data["src"], joined)
        except Exception:
            pass

    def _phonetic_chip(self, parent, label, ipa, accent):
        chip = tk.Frame(parent, bg=C["tag"])
        chip.pack(side="left", padx=(0, 8))
        tk.Label(chip, text=label, bg=C["tag"], fg=C["accent"],
                 font=(FONT_FAMILY, 9, "bold"), pady=2).pack(
            side="left", padx=(7, 2))
        tk.Label(chip, text="/%s/" % ipa, bg=C["tag"], fg=C["sub"],
                 font=("Consolas", 9), pady=2).pack(side="left")
        btn = tk.Label(chip, text="▶", bg=C["tag"], fg=C["accent"],
                       font=("Segoe UI Symbol", 8), pady=2,
                       cursor="hand2")
        btn.pack(side="left", padx=(2, 7))
        btn.bind("<Button-1>", lambda e: speak(self.data["src"], accent))

    def _finish(self):
        self._prev_hwnd = ctypes.windll.user32.GetForegroundWindow()
        self._apply_effects()
        self._place_near_cursor()
        force_foreground(self.winfo_id())
        self.focus_force()

    def _apply_effects(self):
        # 标准窗口：阴影与圆角由系统提供，无需额外处理
        return

    def _place_near_cursor(self):
        cx, cy = win32api.GetCursorPos()
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), self.WIDTH)
        h = self.winfo_reqheight()
        wa = workarea_at(cx, cy)
        x, y = cx + 14, cy + 18
        if x + w > wa.right - 6:
            x = cx - w - 14
        if y + h > wa.bottom - 6:
            y = cy - h - 12
        x = max(wa.left + 6, x)
        y = max(wa.top + 6, y)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def close(self):
        prev = getattr(self, "_prev_hwnd", None)
        try:
            self.destroy()
        except Exception:
            pass
        if prev and ctypes.windll.user32.IsWindow(prev):
            try:
                ctypes.windll.user32.SetForegroundWindow(prev)
            except Exception:
                pass


# ---------------------------------------------------------------- TipWindow

class TipWindow(tk.Toplevel):
    def __init__(self, master, text, autoclose=2.8):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=C["line"])
        box = tk.Frame(self, bg=C["bg"])
        box.pack(fill="both", expand=True, padx=1, pady=1)
        row = tk.Frame(box, bg=C["bg"])
        row.pack(padx=16, pady=12)
        tk.Label(row, text="ℹ", bg=C["bg"], fg=C["accent"],
                 font=("Segoe UI Symbol", 14)).pack(side="left", padx=(0, 9))
        tk.Label(row, text=text, bg=C["bg"], fg=C["dst"], justify="left",
                 font=(FONT_FAMILY, 10)).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(40, lambda: self._place(autoclose))

    def _place(self, autoclose):
        cx, cy = win32api.GetCursorPos()
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        wa = workarea_at(cx, cy)
        x = min(max(cx - w // 2, wa.left + 8), wa.right - w - 8)
        y = min(max(cy + 20, wa.top + 8), wa.bottom - h - 8)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.focus_force()
        if autoclose:
            self.after(int(autoclose * 1000), self.destroy)


class LoadingWindow(tk.Toplevel):
    """工作中提示（不自动关闭）：OCR / 翻译期间让用户明确知道程序正在处理。"""

    def __init__(self, master, text):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=C["line"])
        box = tk.Frame(self, bg=C["bg"])
        box.pack(fill="both", expand=True, padx=1, pady=1)
        row = tk.Frame(box, bg=C["bg"])
        row.pack(padx=18, pady=12)
        self.dot = tk.Label(row, text="●", bg=C["bg"], fg=C["accent"],
                            font=("Segoe UI Symbol", 13))
        self.dot.pack(side="left", padx=(0, 10))
        self.var = tk.StringVar(value=text)
        tk.Label(row, textvariable=self.var, bg=C["bg"], fg=C["dst"],
                 justify="left", font=(FONT_FAMILY, 10)).pack(side="left")
        self._n = 0
        self._tick()
        self.after(40, self._place)

    def set_text(self, text):
        self.var.set(text)

    def _tick(self):
        if not self.winfo_exists():
            return
        self._n = (self._n + 1) % 4
        self.dot.configure(text="●" if self._n in (0, 1) else "○")
        self.after(380, self._tick)

    def _place(self):
        try:
            cx, cy = win32api.GetCursorPos()
            self.update_idletasks()
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            wa = workarea_at(cx, cy)
            x = min(max(cx - w // 2, wa.left + 8), wa.right - w - 8)
            y = min(max(cy + 22, wa.top + 8), wa.bottom - h - 8)
            self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except Exception:
            pass

    def close(self):
        try:
            self.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 设置窗

class SettingsWindow(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.snap = app.cfg.snapshot()
        self.title("快捷翻译 · 设置")
        self.configure(bg=C["bg"])
        self.resizable(True, True)
        self.s = self.winfo_fpixels("1i") / 96.0
        self.minsize(int(560 * self.s), int(560 * self.s))

        # 可滚动主体
        outer = tk.Frame(self, bg=C["bg"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=C["bg"], highlightthickness=0,
                           width=int(560 * self.s),
                           height=int(600 * self.s))
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=C["bg"])
        win_id = canvas.create_window((0, 0), window=body, anchor="nw",
                                      width=int(540 * self.s))
        body.bind("<Configure>",
                  lambda e: canvas.configure(
                      scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        def wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind_all("<MouseWheel>", wheel)
        canvas.bind("<Destroy>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        pad = dict(padx=18)
        # --- 快捷键
        g1 = tk.LabelFrame(body, text=" 快捷键 ", bg=C["bg"], fg=C["dst"],
                           font=(FONT_FAMILY, 10, "bold"))
        g1.pack(fill="x", pady=(14, 6), **pad)
        self.hk_vars = {}
        self.hk_btns = {}
        for slot, label in (("hotkey_translate", "划词翻译"),
                            ("hotkey_ocr", "截图 OCR 翻译"),
                            ("hotkey_ai", "AI 提问")):
            self._hk_row(g1, slot, label)

        # --- 百度官方
        g2 = tk.LabelFrame(body, text=" 百度翻译官方 API（可选） ",
                           bg=C["bg"], fg=C["dst"],
                           font=(FONT_FAMILY, 10, "bold"))
        g2.pack(fill="x", pady=6, **pad)
        self.bd_appid = self._entry(g2, "APP ID", self.snap["baidu_appid"])
        self.bd_key = self._entry(g2, "密钥", self.snap["baidu_key"],
                                  secret=True)
        tk.Label(g2, text="免费申请：fanyi-api.baidu.com（标准版免费，详见说明）",
                 bg=C["bg"], fg=C["sub"],
                 font=(FONT_FAMILY, 8)).pack(anchor="w", padx=8, pady=(2, 8))

        # --- AI
        g3 = tk.LabelFrame(body, text=" AI 助手（OpenAI 兼容） ",
                           bg=C["bg"], fg=C["dst"],
                           font=(FONT_FAMILY, 10, "bold"))
        g3.pack(fill="x", pady=6, **pad)
        row = tk.Frame(g3, bg=C["bg"]); row.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(row, text="服务商：", bg=C["bg"], fg=C["dst"],
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.preset_var = tk.StringVar()
        names = [p[0] for p in AI_PRESETS]
        cb = ttk.Combobox(row, textvariable=self.preset_var, values=names,
                          state="readonly", width=18)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", self._on_preset)
        self.ai_base = self._entry(g3, "接口地址 Base URL",
                                   self.snap["ai_base_url"])
        self.ai_key = self._entry(g3, "API Key", self.snap["ai_key"],
                                  secret=True)
        self.ai_model = self._model_selector(g3, "模型 Model",
                                             self.snap["ai_model"])
        self.ai_domain = self._entry(g3, "专业领域（可选，如：安全工程/煤矿热动力）",
                                     self.snap["ai_domain"])
        tk.Label(g3, text="密钥仅保存在本机 config.ini；申请教程见使用说明。",
                 bg=C["bg"], fg=C["sub"],
                 font=(FONT_FAMILY, 8)).pack(anchor="w", padx=8, pady=(2, 8))
        # 回显预设名
        cur = self.snap["ai_preset"]
        self.preset_var.set(cur if cur in names else "自定义")

        # --- 常规
        g4 = tk.LabelFrame(body, text=" 常规 ", bg=C["bg"], fg=C["dst"],
                           font=(FONT_FAMILY, 10, "bold"))
        g4.pack(fill="x", pady=6, **pad)
        self.var_copy = tk.BooleanVar(value=self.snap["auto_copy"])
        self.var_start = tk.BooleanVar(value=self.snap["auto_startup"])
        self.var_hist = tk.BooleanVar(value=self.snap["history"])
        for var, txt in ((self.var_copy, "译文自动复制"),
                         (self.var_start, "开机自动启动"),
                         (self.var_hist, "保存查词历史")):
            tk.Checkbutton(g4, text=txt, variable=var, bg=C["bg"],
                           fg=C["dst"], font=(FONT_FAMILY, 9),
                           activebackground=C["bg"]).pack(
                anchor="w", padx=8, pady=2)
        rw = tk.Frame(g4, bg=C["bg"]); rw.pack(fill="x", padx=8, pady=4)
        tk.Label(rw, text="发音偏好：", bg=C["bg"], fg=C["dst"],
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.voice_var = tk.StringVar(
            value="美音" if self.snap["voice"] == "us" else "英音")
        ttk.Combobox(rw, textvariable=self.voice_var,
                     values=["美音", "英音"], state="readonly",
                     width=8).pack(side="left", padx=6)
        tk.Label(rw, text="OCR 语言：", bg=C["bg"], fg=C["dst"],
                 font=(FONT_FAMILY, 9)).pack(side="left", padx=(16, 0))
        self.ocr_var = tk.StringVar(value=self.snap["ocr_lang"])
        ttk.Combobox(rw, textvariable=self.ocr_var,
                     values=["en", "zh-Hans-CN"], state="readonly",
                     width=11).pack(side="left", padx=6)
        tk.Frame(g4, height=6, bg=C["bg"]).pack()

        # --- 按钮
        btns = tk.Frame(body, bg=C["bg"])
        btns.pack(fill="x", pady=12, **pad)
        tk.Button(btns, text="保存", width=11, command=self._save,
                  font=(FONT_FAMILY, 10), relief="solid", bg=C["accent"],
                  fg="white", bd=0).pack(side="right", padx=6)
        tk.Button(btns, text="取消", width=11, command=self.destroy,
                  font=(FONT_FAMILY, 10), relief="solid", bg=C["tag"],
                  fg=C["dst"], bd=0).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(60, self._bring)

    def _bring(self):
        try:
            self.update_idletasks()
            self.deiconify()
            w = self.winfo_width()
            h = self.winfo_height()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            self.geometry("+%d+%d" % (max(0, (sw - w) // 2),
                                       max(0, (sh - h) // 2 - 20)))
            force_foreground(self.winfo_id())
        except Exception:
            pass

    # 快捷键行
    def _hk_row(self, parent, slot, label):
        row = tk.Frame(parent, bg=C["bg"]); row.pack(fill="x", padx=8, pady=4)
        tk.Label(row, text=label, bg=C["bg"], fg=C["dst"],
                 font=(FONT_FAMILY, 9), width=14, anchor="w").pack(side="left")
        var = tk.StringVar(value=self.snap[slot])
        ent = tk.Entry(row, textvariable=var, width=18,
                       font=("Consolas", 10), state="readonly",
                       relief="solid")
        ent.pack(side="left", padx=6)
        btn = tk.Button(row, text="录制", width=7,
                        font=(FONT_FAMILY, 9), relief="solid", bd=1,
                        command=lambda: self._record(slot))
        btn.pack(side="left")
        self.hk_vars[slot] = var
        self.hk_btns[slot] = btn

    def _record(self, slot):
        btn = self.hk_btns[slot]
        btn.configure(text="请按键…", state="disabled")
        self.app.unregister_hotkeys()

        def work():
            combo = keyboard.read_hotkey(suppress=False)
            self.app.q.put(("recorded", slot, combo))

        threading.Thread(target=work, daemon=True).start()

    def record_result(self, slot, combo):
        combo = combo.strip().lower()
        # 过滤无效（仅修饰键 / esc）
        mains = [k for k in re.split(r"\+", combo)
                 if k not in ("ctrl", "alt", "shift", "windows", "esc", "")]
        btn = self.hk_btns[slot]
        if mains:
            self.hk_vars[slot].set(combo)
        btn.configure(text="录制", state="normal")
        self.app.register_hotkeys()

    def _on_preset(self, _=None):
        name = self.preset_var.get()
        for n, base, model in AI_PRESETS:
            if n == name:
                self.ai_base.set(base)
                self.ai_model.set(model)
                self._refresh_model_values()
                return

    def _entry(self, parent, label, value, secret=False):
        row = tk.Frame(parent, bg=C["bg"]); row.pack(fill="x", padx=8, pady=3)
        tk.Label(row, text=label, bg=C["bg"], fg=C["dst"],
                 font=(FONT_FAMILY, 9), width=22, anchor="w").pack(side="left")
        var = tk.StringVar(value=value)
        ent = tk.Entry(row, textvariable=var, width=32, show="*" if secret
                       else "", font=("Consolas", 9), relief="solid")
        ent.pack(side="left", fill="x", expand=True, padx=(4, 0))
        return var

    def _model_selector(self, parent, label, value):
        row = tk.Frame(parent, bg=C["bg"]); row.pack(fill="x", padx=8, pady=3)
        tk.Label(row, text=label, bg=C["bg"], fg=C["dst"],
                 font=(FONT_FAMILY, 9), width=22, anchor="w").pack(side="left")
        var = tk.StringVar(value=value)
        self.model_cb = ttk.Combobox(row, textvariable=var, values=[],
                                     width=30)
        self.model_cb.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._refresh_model_values()
        return var

    def _refresh_model_values(self):
        try:
            models = PRESET_MODELS.get(self.preset_var.get(), [])
            self.model_cb.configure(values=models)
        except Exception:
            pass

    def _save(self):
        cfg = self.app.cfg
        cfg.hotkey_translate = self.hk_vars["hotkey_translate"].get()
        cfg.hotkey_ocr = self.hk_vars["hotkey_ocr"].get()
        cfg.hotkey_ai = self.hk_vars["hotkey_ai"].get()
        cfg.baidu_appid = self.bd_appid.get().strip()
        cfg.baidu_key = self.bd_key.get().strip()
        cfg.ai_preset = self.preset_var.get()
        cfg.ai_base_url = self.ai_base.get().strip().rstrip("/")
        cfg.ai_key = self.ai_key.get().strip()
        cfg.ai_model = self.ai_model.get().strip()
        cfg.ai_domain = self.ai_domain.get().strip()
        cfg.auto_copy = bool(self.var_copy.get())
        cfg.auto_startup = bool(self.var_start.get())
        cfg.history = bool(self.var_hist.get())
        cfg.voice = "us" if self.voice_var.get() == "美音" else "uk"
        cfg.ocr_lang = self.ocr_var.get()
        try:
            cfg.save()
        except Exception:
            pass
        set_autostart(cfg.auto_startup)
        self.app.unregister_hotkeys()
        self.app.register_hotkeys()
        self.app.refresh_tray_menu()
        TipWindow(self.app.root, "设置已保存")
        self.destroy()


# ---------------------------------------------------------------- AI 对话窗

class AiWindow(tk.Toplevel):
    def __init__(self, master, app, text):
        super().__init__(master)
        self.app = app
        self.win_id = str(id(self))
        self.title("AI 助手")
        self.configure(bg=C["bg"])
        self.s = self.winfo_fpixels("1i") / 96.0
        self.minsize(int(460 * self.s), int(400 * self.s))
        self.messages = []
        self.sending = False
        self.closed = False
        self.phase = "idle"

        # 动作按钮
        bar = tk.Frame(self, bg=C["tag"])
        bar.pack(fill="x")
        for label, kind in (("详细解释", "explain"),
                            ("翻译并讲解", "translate"),
                            ("润色改写", "polish")):
            tk.Button(bar, text=label, relief="flat", bd=0, bg=C["tag"],
                      fg=C["accent"], font=(FONT_FAMILY, 9), cursor="hand2",
                      activebackground="#E2E8F5",
                      command=lambda k=kind: self._action(k, text)).pack(
                side="left", padx=6, pady=6)

        # 对话区
        mid = tk.Frame(self, bg=C["bg"])
        mid.pack(fill="both", expand=True)
        self.chat = tk.Text(mid, wrap="word", relief="flat", bg=C["bg"],
                            bd=0, font=(FONT_FAMILY, 10), padx=12, pady=10,
                            width=74, height=22, highlightthickness=0)
        csb = tk.Scrollbar(mid, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.chat.pack(side="left", fill="both", expand=True)
        self.chat.tag_config("user", foreground=C["accent"],
                             font=(FONT_FAMILY, 10, "bold"),
                             spacing1=10, spacing3=3)
        self.chat.tag_config("ai", foreground=C["dst"], spacing3=3)
        self.chat.tag_config("note", foreground=C["sub"],
                             font=(FONT_FAMILY, 9))
        self.chat.tag_config("thinktitle", foreground=C["sub"],
                             font=(FONT_FAMILY, 9, "bold"), spacing1=4)
        self.chat.tag_config("think", foreground="#9AA4B2",
                             font=(FONT_FAMILY, 9), spacing3=1)
        self.chat.configure(state="disabled")

        # 未配置时的“打开设置”引导条（默认空，不占空间）
        self.setup_bar = tk.Frame(self, bg=C["bg"])
        self.setup_bar.pack(fill="x")

        # 自由提问提示
        hint = tk.Frame(self, bg=C["tag"])
        hint.pack(fill="x")
        tk.Label(hint,
                 text="可直接在下方输入任何问题（回车发送，Shift+回车换行），像普通 AI 一样自由提问",
                 bg=C["tag"], fg=C["sub"], font=(FONT_FAMILY, 9),
                 anchor="w").pack(fill="x", padx=12, pady=4)

        # 输入区
        bot = tk.Frame(self, bg=C["line"])
        bot.pack(fill="x")
        self.inp = tk.Text(bot, height=2, wrap="word", relief="flat",
                           font=(FONT_FAMILY, 10), padx=10, pady=8,
                           highlightthickness=0)
        self.inp.pack(side="left", fill="both", expand=True)
        self.inp.bind("<Return>", self._enter)
        self.inp.bind("<Shift-Return>", lambda e: None)
        self.inp.bind("<Button-1>",
                      lambda e: self.inp.focus_set(), add="+")
        tk.Button(bot, text="发送", width=8, relief="flat", bd=0,
                  bg=C["accent"], fg="white", font=(FONT_FAMILY, 10),
                  command=self._send_custom).pack(side="right", fill="y",
                                                  padx=8, pady=8)

        self.protocol("WM_DELETE_WINDOW", self._close)
        bind_escape(self, self._close, [self.chat, self.inp])
        self._place_window()
        self.after(80, lambda: self._begin(text))

    def _place_window(self):
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), int(620 * self.s))
        h = max(self.winfo_reqheight(), int(560 * self.s))
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # 初始化
    def _begin(self, text):
        force_foreground(self.winfo_id())
        self.focus_force()
        if not self.app.ai_ready():
            self._note("尚未配置 AI。请先到“设置 → AI 助手”填写接口地址、密钥与模型。")
            tk.Button(self.setup_bar, text="打开设置", relief="flat",
                      bg=C["accent"], fg="white", font=(FONT_FAMILY, 9), bd=0,
                      cursor="hand2",
                      command=self.app.open_settings).pack(pady=6)
            return
        if text:
            self._action("explain", text)
        else:
            self._note("可在下方输入问题，或先选中文字再按 AI 快捷键。")
            self.inp.focus_set()

    def _close(self):
        self.closed = True
        self.app.ai_wins.pop(self.win_id, None)
        self.destroy()

    # 动作
    def _action(self, kind, text):
        if not text or self.sending:
            return
        if not self.app.ai_ready():
            self._note("请先在设置中配置 AI。")
            return
        prompts = {
            "explain": "请简洁解释下面的内容；若是缩写或专有名词，先给英文全称再解释，直接讲重点，不要客套和铺垫：\n",
            "translate": "请先准确翻译下面的内容，再用几句话简要讲解关键点，不要长篇展开：\n",
            "polish": "请润色下面的内容使其更地道，并简要说明主要改动：\n",
        }
        self._submit(prompts[kind] + text)

    def _enter(self, e):
        if e.state & 0x1:   # Shift 按下 → 换行
            return
        self._send_custom()
        return "break"

    def _send_custom(self):
        q = self.inp.get("1.0", "end").strip()
        if not q or self.sending:
            return
        self.inp.delete("1.0", "end")
        self._submit(q)

    def _submit(self, user_text):
        self._append("我：\n" + user_text + "\n", "user")
        self.messages.append({"role": "user", "content": user_text})
        self._show_waiting()
        self.sending = True
        self.app.pool.submit(self.app.ai_stream, self.win_id,
                             self._system(), list(self.messages))

    def _show_waiting(self):
        self.chat.configure(state="normal")
        self.chat.mark_set("wait_start", "end-1c")
        self.chat.mark_gravity("wait_start", "left")
        self.chat.insert("end", "AI 思考中，请稍候…", "note")
        self.chat.mark_set("wait_end", "end-1c")
        self.chat.see("end")
        self.chat.configure(state="disabled")
        self.phase = "wait"

    def _clear_waiting(self):
        try:
            self.chat.delete("wait_start", "wait_end")
        except Exception:
            pass

    def _system(self):
        base = ("你是一个简洁、直接的 AI 助手，使用简体中文回答。"
                "直接针对问题本身作答：不要客套开场白，不要复述或铺垫用户的问题，"
                "也不要主动罗列用户的背景信息；先给结论或答案，简明扼要，"
                "只有在问题确实需要时才展开。遇到缩写或专有名词可先给英文全称。")
        d = self.app.cfg.ai_domain.strip()
        if d:
            base += ("用户的学习/研究方向是“%s”，但仅当问题确实与该方向直接相关时才可参考；"
                     "其他问题按通用常识正常回答，不要主动把话题引向该方向，也不要刻意靠拢。"
                     % d)
        return base

    # 由主线程调用
    def _append(self, text, tag):
        if self.closed:
            return
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _note(self, text):
        self._append(text + "\n", "note")

    def on_reasoning(self, token):
        self.chat.configure(state="normal")
        if self.phase != "thinking":
            self._clear_waiting()
            self.chat.insert("end", "思考过程：\n", "thinktitle")
            self.phase = "thinking"
        self.chat.insert("end", token, "think")
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def on_token(self, token):
        self.chat.configure(state="normal")
        if self.phase in ("wait", "thinking"):
            self._clear_waiting()
            if self.phase == "thinking":
                self.chat.insert("end", "\n")
            self.chat.insert("end", "AI：\n", "ai")
            self.phase = "answering"
        self.chat.insert("end", token, "ai")
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def on_error(self, msg):
        self.chat.configure(state="normal")
        self._clear_waiting()
        if self.phase == "thinking":
            self.chat.insert("end", "\n")
        self.chat.insert("end", "AI：\n[出错] " + msg + "\n", "note")
        self.chat.see("end")
        self.chat.configure(state="disabled")
        self.sending = False
        self.phase = "idle"
        self.inp.focus_set()

    def on_done(self):
        self.chat.configure(state="normal")
        if self.phase != "answering":
            self._clear_waiting()
            self.chat.insert("end", "AI：\n（未返回内容）\n", "note")
        else:
            self.chat.insert("end", "\n", "ai")
        self.chat.see("end")
        self.chat.configure(state="disabled")
        self.sending = False
        self.phase = "idle"
        self.inp.focus_set()

    def set_ai_reply(self, reply):
        self.messages.append({"role": "assistant", "content": reply})


# ---------------------------------------------------------------- 托盘

def fallback_icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=14, fill=(64, 128, 245, 255))
    try:
        f = ImageFont_truetype()
        d.text((20, 12), "译", font=f, fill=(255, 255, 255, 255))
    except Exception:
        d.text((22, 18), "A", fill=(255, 255, 255, 255))
    return img


def ImageFont_truetype():
    from PIL import ImageFont
    for fp in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc"):
        if os.path.exists(fp):
            return ImageFont.truetype(fp, 34)
    return None


def build_tray(app):
    if os.path.exists(ICON_PATH):
        icon_img = Image.open(ICON_PATH)
    else:
        icon_img = fallback_icon_image()

    def cmd(name):
        return lambda icon=None, item=None: app.q.put(("tray", name))

    menu = Menu(
        Item("打开设置", cmd("open_settings"), default=True),
        Menu.SEPARATOR,
        Item(lambda i: "划词翻译\t" +
             pretty_hotkey(app.cfg.hotkey_translate), cmd("translate")),
        Item(lambda i: "截图翻译\t" +
             pretty_hotkey(app.cfg.hotkey_ocr), cmd("ocr")),
        Item(lambda i: "AI 提问\t" +
             pretty_hotkey(app.cfg.hotkey_ai), cmd("ai")),
        Menu.SEPARATOR,
        Item("开机自启", cmd("toggle_startup"),
             checked=lambda i: app.cfg.auto_startup),
        Item("译文自动复制", cmd("toggle_copy"),
             checked=lambda i: app.cfg.auto_copy),
        Menu.SEPARATOR,
        Item("查看历史记录", cmd("history")),
        Item("使用说明", cmd("help")),
        Item("退出", cmd("quit")),
    )
    return pystray.Icon("DoubaoFanyi", icon_img, "快捷翻译", menu)


# ---------------------------------------------------------------- 主控

class App:
    def __init__(self):
        self.cfg = Config(CONFIG_PATH)
        if self.cfg.auto_startup and not is_autostart():
            set_autostart(True)
        if not self.cfg.auto_startup and is_autostart():
            set_autostart(False)

        self.root = tk.Tk()
        self.root.withdraw()
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(6)
        self.busy = False
        self.hotkeys = []
        self.cur_window = None
        self.settings_win = None
        self.ai_wins = {}
        self._shot = None
        self._mon = None

        self.register_hotkeys()
        self.tray = build_tray(self)
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.root.after(150, self._pump)
        self.root.mainloop()

    # ---- 快捷键
    def register_hotkeys(self):
        for combo, tag in ((self.cfg.hotkey_translate, "translate"),
                           (self.cfg.hotkey_ocr, "ocr"),
                           (self.cfg.hotkey_ai, "ai")):
            try:
                if tag == "ocr":
                    def ocr_fired():
                        # 在按键被传递、目标弹出菜单关闭之前尽快抓屏
                        def task():
                            try:
                                img, mon = capture_virtual()
                                self.q.put(("ocr_shot", img, mon))
                            except Exception as e:
                                self.q.put(("tip", "截图初始化失败：%s" % e))
                        threading.Thread(target=task, daemon=True).start()
                    hid = keyboard.add_hotkey(combo, ocr_fired,
                                              suppress=True, timeout=0.5)
                else:
                    hid = keyboard.add_hotkey(
                        combo, lambda t=tag: self.q.put(("hotkey", t)),
                        suppress=True, timeout=0.5)
                self.hotkeys.append(hid)
            except Exception as e:
                self._log("注册快捷键 %s 失败：%s" % (combo, e))

    def unregister_hotkeys(self):
        for hid in self.hotkeys:
            try:
                keyboard.remove_hotkey(hid)
            except Exception:
                pass
        self.hotkeys = []

    def refresh_tray_menu(self):
        try:
            self.tray.update_menu()
        except Exception:
            pass

    # ---- 消息泵
    def _pump(self):
        try:
            while True:
                self._dispatch(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    def _dispatch(self, msg):
        kind = msg[0]
        if kind == "hotkey":
            self.on_hotkey(msg[1])
        elif kind == "tray":
            self.on_tray(msg[1])
        elif kind == "result":
            self.busy = False
            self.show_result(msg[1])
        elif kind == "tip":
            self.busy = False
            self.show_tip(msg[1])
        elif kind == "loading":
            self.show_loading(msg[1])
        elif kind == "ocr_region":
            self.on_ocr_region(msg[1])
        elif kind == "ocr_shot":
            self.on_ocr_shot(msg[1], msg[2])
        elif kind == "open_settings":
            self.open_settings()
        elif kind == "recorded":
            if self.settings_win and self.settings_win.winfo_exists():
                self.settings_win.record_result(msg[1], msg[2])
        elif kind == "ai_open":
            self.open_ai(msg[1])
        elif kind == "ai_reply":
            win = self.ai_wins.get(msg[1])
            if win and win.winfo_exists():
                win.set_ai_reply(msg[2])
        elif kind == "ai_reasoning":
            win = self.ai_wins.get(msg[1])
            if win and win.winfo_exists():
                win.on_reasoning(msg[2])
        elif kind in ("ai_token", "ai_done", "ai_error"):
            win = self.ai_wins.get(msg[1])
            if win and win.winfo_exists():
                if kind == "ai_token":
                    win.on_token(msg[2])
                elif kind == "ai_error":
                    win.on_error(msg[2])
                else:
                    win.on_done()

    # ---- 设置
    def open_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            try:
                force_foreground(self.settings_win.winfo_id())
                self.settings_win.lift()
                return
            except Exception:
                pass
        self.settings_win = SettingsWindow(self.root, self)

    def ai_ready(self):
        return bool(self.cfg.ai_base_url and self.cfg.ai_key
                    and self.cfg.ai_model)

    # ---- 热键入口
    def on_hotkey(self, which):
        if which == "ai":
            self.pool.submit(self.flow_ai)
            return
        if self.busy:
            return
        self.busy = True
        if which == "translate":
            self.pool.submit(self.flow_translate)
        else:
            self.begin_ocr()

    # ---- 划词
    def flow_translate(self):
        try:
            text = grab_selected()
            if not text:
                self.q.put(("tip", "未获取到选中的文字\n请先选中内容，再按快捷键"))
                return
            self.q.put(("loading", "正在翻译…"))
            self.translate_and_show(text)
        except Exception as e:
            self.q.put(("tip", "出错了：%s" % e))

    def translate_and_show(self, text, ocr_fallback=False):
        try:
            if _count_lines(text) >= 2:
                # 多行：逐行翻译并保持行序一一对应
                def _prog(done, total):
                    self.q.put(("loading",
                               "正在翻译… %d/%d 行" % (done, total)))

                pairs, engine = translate_block(
                    text, self.cfg, on_progress=_prog)
                dst = "\n".join(d for _s, d in pairs if d)
                data = {"src": text, "mode": "sentence", "dst": dst,
                        "pairs": pairs, "engine": engine,
                        "ocr_fallback": ocr_fallback}
            elif is_word_like(text):
                groups, uk, us = collect_word(text, self.cfg)
                if groups:
                    data = {"src": text, "mode": "word", "groups": groups,
                            "uk": uk, "us": us, "engine": "多来源",
                            "ocr_fallback": ocr_fallback}
                    dst = "\n".join(it for g in groups for it in g["items"])
                else:
                    dst, engine = translate_sentence(text, self.cfg)
                    data = {"src": text, "mode": "sentence", "dst": dst,
                            "engine": engine, "ocr_fallback": ocr_fallback}
            else:
                dst, engine = translate_sentence(text, self.cfg)
                data = {"src": text, "mode": "sentence", "dst": dst,
                        "engine": engine, "ocr_fallback": ocr_fallback}
            if self.cfg.auto_copy:
                clipboard_set_text(dst)
            if self.cfg.history:
                append_history(text, dst)
            self.q.put(("result", data))
        except Exception as e:
            self.q.put(("tip", str(e)))

    # ---- OCR
    def on_ocr_shot(self, img, mon):
        if self.busy:
            return
        try:
            self.busy = True
            self._shot, self._mon = img, mon
            self._open_selector(img, mon)
        except Exception as e:
            self.busy = False
            self.show_tip("截图初始化失败：%s" % e)

    def begin_ocr(self):
        try:
            img, mon = capture_virtual()
            self._shot, self._mon = img, mon
            self._open_selector(img, mon)
        except Exception as e:
            self.busy = False
            self.show_tip("截图初始化失败：%s" % e)

    def _open_selector(self, img, mon):
        # 遮罩几何与截图、裁剪坐标完全同源（mon 即 mss 虚拟屏），避免坐标错位
        RegionSelector(
            self.root, mon["left"], mon["top"], mon["width"], mon["height"],
            on_done=lambda bbox: self.q.put(("ocr_region", bbox)),
            background=img)

    def on_ocr_region(self, bbox):
        if not bbox:
            self.busy = False
            return
        # 框选完成立刻给出反馈，遮罩关闭后马上进入“工作中”状态
        self.show_loading("正在识别画面文字…")
        self.pool.submit(self.flow_ocr, bbox)

    def flow_ocr(self, bbox):
        try:
            mon = self._mon
            shot = self._shot
            W, H = shot.size
            left, top, right, bottom = bbox
            pad = 10  # 选区四周向外扩，避免切掉字边缘
            box = (max(0, left - mon["left"] - pad),
                   max(0, top - mon["top"] - pad),
                   min(W, right - mon["left"] + pad),
                   min(H, bottom - mon["top"] + pad))
            crop = _enlarge_for_ocr(shot.crop(box))
            text, fb = ocr_recognize(crop, self.cfg.ocr_lang)
            text = clean_text(text)
            if not text:
                self.q.put(("tip", "未识别到文字，请重新框选（可把框选范围放大一些）"))
                return
            n = _count_lines(text)
            if n >= 2:
                self.q.put(("loading", "正在翻译…（共 %d 行）" % n))
            else:
                self.q.put(("loading", "正在翻译…"))
            self.translate_and_show(text, ocr_fallback=bool(fb))
        except OcrLangError as e:
            self.q.put(("tip", str(e)))
            try:
                os.startfile("ms-settings:regionlanguage")
            except Exception:
                pass
        except Exception as e:
            self.q.put(("tip", "OCR 失败：%s" % e))

    # ---- AI
    def flow_ai(self):
        text = grab_selected()
        self.q.put(("ai_open", text))

    def open_ai(self, text):
        win = AiWindow(self.root, self, text or "")
        self.ai_wins[win.win_id] = win

    def ai_stream(self, win_id, system, messages):
        url = self.cfg.ai_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + self.cfg.ai_key,
                   "Content-Type": "application/json"}
        body = {"model": self.cfg.ai_model,
                "messages": [{"role": "system", "content": system}] + messages,
                "stream": True}
        reply = ""
        try:
            r = requests.post(url, headers=headers, json=body, stream=True,
                              timeout=(10, 90))
            if r.status_code != 200:
                self.q.put(("ai_error", win_id,
                            "HTTP %s %s" % (r.status_code, r.text[:200])))
                return
            rbuf, cbuf = [], []
            last = [time.time()]

            def flush(force=False):
                if not force and time.time() - last[0] < 0.1:
                    return
                if rbuf:
                    self.q.put(("ai_reasoning", win_id, "".join(rbuf)))
                    rbuf.clear()
                if cbuf:
                    self.q.put(("ai_token", win_id, "".join(cbuf)))
                    cbuf.clear()
                last[0] = time.time()

            for raw in r.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore")
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    piece = json.loads(payload)
                    delta = (piece["choices"][0].get("delta") or {})
                    token = delta.get("content")
                    reason = delta.get("reasoning_content")
                except Exception:
                    token = None
                    reason = None
                if reason:
                    rbuf.append(reason)
                if token:
                    cbuf.append(token)
                    reply += token
                flush()
            flush(force=True)
            self.q.put(("ai_reply", win_id, reply))
            self.q.put(("ai_done", win_id))
        except Exception as e:
            self.q.put(("ai_error", win_id, str(e)))

    # ---- 展示
    def show_result(self, data):
        if self.cur_window is not None:
            try:
                self.cur_window.close()
            except Exception:
                pass
        self.cur_window = ResultWindow(self.root, data, self.cfg, self)

    def show_tip(self, text):
        if self.cur_window is not None:
            try:
                self.cur_window.close()
            except Exception:
                pass
        self.cur_window = TipWindow(self.root, text)

    def show_loading(self, text):
        cur = self.cur_window
        if isinstance(cur, LoadingWindow):
            try:
                if cur.winfo_exists():
                    cur.set_text(text)
                    return
            except Exception:
                pass
        elif cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        self.cur_window = LoadingWindow(self.root, text)

    # ---- 托盘动作
    def on_tray(self, name):
        if name == "translate":
            if not self.busy:
                self.busy = True
                self.pool.submit(self.flow_translate)
        elif name == "ocr":
            if not self.busy:
                self.busy = True
                self.begin_ocr()
        elif name == "ai":
            self.pool.submit(self.flow_ai)
        elif name == "open_settings":
            self.open_settings()
        elif name == "toggle_startup":
            v = not self.cfg.auto_startup
            self.cfg.auto_startup = v
            set_autostart(v)
            try:
                self.cfg.save()
            except Exception:
                pass
        elif name == "toggle_copy":
            v = not self.cfg.auto_copy
            self.cfg.auto_copy = v
            try:
                self.cfg.save()
            except Exception:
                pass
        elif name == "history":
            if os.path.exists(HISTORY_PATH):
                try:
                    os.startfile(HISTORY_PATH)
                except Exception:
                    self.show_tip("无法打开历史记录")
            else:
                self.show_tip("暂无历史记录")
        elif name == "help":
            md = os.path.join(APP_DIR, "使用说明.md")
            if os.path.exists(md):
                try:
                    os.startfile(md)
                    return
                except Exception:
                    pass
            self.show_tip("Ctrl+Alt+E 划词翻译\nCtrl+Alt+S 截图翻译\nCtrl+Alt+A AI 提问")
        elif name == "quit":
            self.quit()

    # ---- 日志/退出
    def _log(self, text):
        try:
            with open(os.path.join(APP_DIR, "error.log"), "a",
                      encoding="utf-8") as f:
                f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                      text))
        except Exception:
            pass

    def quit(self):
        try:
            self.unregister_hotkeys()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)


def single_instance():
    ctypes.windll.kernel32.CreateMutexW(None, False,
                                        "Global\\DoubaoFanyi_Mutex")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(
            0, "快捷翻译已经在运行中。\n如需操作，请查看屏幕右下角的托盘图标。",
            "快捷翻译", 0x40)
        return False
    return True


def main():
    if not single_instance():
        return
    try:
        App()
    except Exception:
        try:
            import traceback
            with open(os.path.join(APP_DIR, "error.log"), "a",
                      encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        ctypes.windll.user32.MessageBoxW(
            0, "程序启动失败，详情见 error.log。", "快捷翻译", 0x10)


if __name__ == "__main__":
    main()
