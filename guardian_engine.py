import os, json, time, ccxt, requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CFG = {
    "NAME": "System-B (10-Coin Arena Pro)",
    "SYMBOLS": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "SUI/USDT", "LINK/USDT"],
    "CAP": 50.0, "RISK": 0.02, "LEV": 3, "RR": 3.0, "ATR_M": 1.6, "FEE": 0.0005, "DAYS": 1500
}

def send_tg(msg):
    token = os.environ.get("TG_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if token and chat_id:
        try:
            host = "api." + "telegram.org"
            requests.post(f"https://{host}/bot{token}/sendMessage", json={"chat_id": chat_id, "text": msg}, timeout=10)
        except Exception as e:
            print("TG 發送失敗:", e)

def load_arena_state():
    if os.path.exists("arena_14d_state.json"):
        with open("arena_14d_state.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {"capital": CFG["CAP"], "positions": {}, "history": [], "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

def check_news():
    kws = ["fomc", "cpi", "powell", "rate hike", "war", "attack", "hack", "exploit", "bankruptcy", "sec", "whale dump"]
    try:
        sub, dom, path = "min-api.", "cryptocompare.com", "/data/v2/news/?lang=EN"
        raw = requests.get(f"https://{sub}{dom}{path}", timeout=10).json().get("Data", [])
        data = raw[:15] if isinstance(raw, list) else []
        now = datetime.now(timezone.utc).timestamp()
        for it in data:
            if isinstance(it, dict) and (now - it.get("published_on", 0) <= 7200):
                t = str(it.get("title", "")).lower()
                for k in kws:
                    if k in t:
                        return False, f"警報 [{k.upper()}]: {it.get('title')}"
        return True, "宏觀與鏈上新聞安全"
    except Exception:
        return True, "新聞源備援通過"

def get_ohlcv(ex, sym, tf, days):
    since = ex.milliseconds() - days * 86400000
    rows = []
    while since < ex.milliseconds():
        b = ex.fetch_ohlcv(sym, timeframe=tf, since=since, limit=300)
        if not b: break
        rows.extend(b)
        since = b[-1][0] + 1
        time.sleep(0.1)
    return pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']).drop_duplicates('timestamp').sort_values('timestamp').reset_index(drop=True)

def add_ind(d1h, d4h):
    d4h['e50'] = d4h['close'].ewm(span=50, adjust=False).mean()
    d4h['e200'] = d4h['close'].ewm(span=200, adjust=False).mean()
    d4h['bull'] = (d4h['close'] > d4h['e50']) & (d4h['e50'] > d4h['e200'])
    d4h['bear'] = (d4h['close'] < d4h['e50']) & (d4h['e50'] < d4h['e200'])
    d4h['regime'] = np.select([d4h['bull'], d4h['bear']], ['牛市 (Bull)', '熊市 (Bear)'], default='震盪市 (Range)')

    h, l, c = d4h['high'], d4h['low'], d4h['close']
    pdm = np.where(h.diff().clip(lower=0) > (-l.diff()).clip(lower=0), h.diff().clip(lower=0), 0)
    mdm = np.where((-l.diff()).clip(lower=0) > h.diff().clip(lower=0), (-l.diff()).clip(lower=0), 0)
    atr4 = pd.Series(np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))).rolling(14).mean()
    pdi = 100 * pd.Series(pdm).rolling(14).mean() / atr4
    mdi = 100 * pd.Series(mdm).rolling(14).mean() / atr4
    d4h['adx'] = ((abs(pdi - mdi) / (pdi + mdi)) * 100).rolling(14).mean()

    df = pd.merge_asof(d1h, d4h[['timestamp', 'bull', 'bear', 'regime', 'adx']], on='timestamp', direction='backward')
    df['e21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['sh'] = df['high'].rolling(10).max().shift(1)
    df['sl'] = df['low'].rolling(10).min().shift(1)
    df['vma'] = df['volume'].rolling(20).mean()
    d = df['close'].diff()
    df['rsi'] = 100 - (100 / (1 + d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))
    df['atr'] = pd.Series(np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))).rolling(14).mean()

    ok = (df['adx'] > 22) & (df['volume'] > df['vma'] * 1.2)
    df['lsig'] = df['bull'] & ok & (df['low'].shift(1) <= df['e21'].shift(1)) & (df['close'] > df['e21']) & (df['close'] > df['open']) & (df['rsi'] < 66)
    df['ssig'] = df['bear'] & ok & (df['high'].shift(1) >= df['e21'].shift(1)) & (df['close'] < df['e21']) & (df['close'] < df['open']) & (df['rsi'] > 34)
    return df.dropna().reset_index(drop=True)
import os, json, time, ccxt, requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CFG = {
    "NAME": "System-B (10-Coin Arena Pro)",
    "SYMBOLS": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "SUI/USDT", "LINK/USDT"],
    "CAP": 50.0, "RISK": 0.02, "LEV": 3, "RR": 3.0, "ATR_M": 1.6, "FEE": 0.0005, "DAYS": 1500
}

def send_tg(msg):
    token = os.environ.get("TG_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if token and chat_id:
        try:
            host = "api." + "telegram.org"
            requests.post(f"https://{host}/bot{token}/sendMessage", json={"chat_id": chat_id, "text": msg}, timeout=10)
        except Exception as e:
            print("TG 發送失敗:", e)

def load_arena_state():
    if os.path.exists("arena_14d_state.json"):
        with open("arena_14d_state.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {"capital": CFG["CAP"], "positions": {}, "history": [], "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

def check_news():
    kws = ["fomc", "cpi", "powell", "rate hike", "war", "attack", "hack", "exploit", "bankruptcy", "sec", "whale dump"]
    try:
        sub, dom, path = "min-api.", "cryptocompare.com", "/data/v2/news/?lang=EN"
        raw = requests.get(f"https://{sub}{dom}{path}", timeout=10).json().get("Data", [])
        data = raw[:15] if isinstance(raw, list) else []
        now = datetime.now(timezone.utc).timestamp()
        for it in data:
            if isinstance(it, dict) and (now - it.get("published_on", 0) <= 7200):
                t = str(it.get("title", "")).lower()
                for k in kws:
                    if k in t:
                        return False, f"警報 [{k.upper()}]: {it.get('title')}"
        return True, "宏觀與鏈上新聞安全"
    except Exception:
        return True, "新聞源備援通過"

def get_ohlcv(ex, sym, tf, days):
    since = ex.milliseconds() - days * 86400000
    rows = []
    while since < ex.milliseconds():
        b = ex.fetch_ohlcv(sym, timeframe=tf, since=since, limit=300)
        if not b: break
        rows.extend(b)
        since = b[-1][0] + 1
        time.sleep(0.1)
    return pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']).drop_duplicates('timestamp').sort_values('timestamp').reset_index(drop=True)

def add_ind(d1h, d4h):
    d4h['e50'] = d4h['close'].ewm(span=50, adjust=False).mean()
    d4h['e200'] = d4h['close'].ewm(span=200, adjust=False).mean()
    d4h['bull'] = (d4h['close'] > d4h['e50']) & (d4h['e50'] > d4h['e200'])
    d4h['bear'] = (d4h['close'] < d4h['e50']) & (d4h['e50'] < d4h['e200'])
    d4h['regime'] = np.select([d4h['bull'], d4h['bear']], ['牛市 (Bull)', '熊市 (Bear)'], default='震盪市 (Range)')

    h, l, c = d4h['high'], d4h['low'], d4h['close']
    pdm = np.where(h.diff().clip(lower=0) > (-l.diff()).clip(lower=0), h.diff().clip(lower=0), 0)
    mdm = np.where((-l.diff()).clip(lower=0) > h.diff().clip(lower=0), (-l.diff()).clip(lower=0), 0)
    atr4 = pd.Series(np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))).rolling(14).mean()
    pdi = 100 * pd.Series(pdm).rolling(14).mean() / atr4
    mdi = 100 * pd.Series(mdm).rolling(14).mean() / atr4
    d4h['adx'] = ((abs(pdi - mdi) / (pdi + mdi)) * 100).rolling(14).mean()

    df = pd.merge_asof(d1h, d4h[['timestamp', 'bull', 'bear', 'regime', 'adx']], on='timestamp', direction='backward')
    df['e21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['sh'] = df['high'].rolling(10).max().shift(1)
    df['sl'] = df['low'].rolling(10).min().shift(1)
    df['vma'] = df['volume'].rolling(20).mean()
    d = df['close'].diff()
    df['rsi'] = 100 - (100 / (1 + d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))
    df['atr'] = pd.Series(np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))).rolling(14).mean()

    ok = (df['adx'] > 22) & (df['volume'] > df['vma'] * 1.2)
    df['lsig'] = df['bull'] & ok & (df['low'].shift(1) <= df['e21'].shift(1)) & (df['close'] > df['e21']) & (df['close'] > df['open']) & (df['rsi'] < 66)
    df['ssig'] = df['bear'] & ok & (df['high'].shift(1) >= df['e21'].shift(1)) & (df['close'] < df['e21']) & (df['close'] < df['open']) & (df['rsi'] > 34)
    return df.dropna().reset_index(drop=True)
