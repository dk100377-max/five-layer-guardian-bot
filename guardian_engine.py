import os
import json
import time
import ccxt
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

# ==========================================
# 【系統 B：Guardian-B 競賽專用參數 (50 USDT 賽制)】
# ==========================================
CONFIG = {
    "MODEL_NAME": "System-B (Guardian AI)",
    "SYMBOL": "BTC/USDT",
    "INITIAL_CAPITAL": 50.0,      # 競賽統一初始本金: 50 USDT
    "RISK_PER_TRADE": 0.02,       # 單筆動態風險 2.0% (初始 1.00 U，隨獲利複利放大)
    "LEVERAGE": 3,                # 3倍逐倉 (安全防爆)
    "RR_RATIO": 3.0,              # 目標盈虧比 1:3 (勝過系統A的1:2)
    "ATR_STOP_MULT": 1.5,         # 動態防插針緩衝 (躲開洗盤)
    "FEE_RATE": 0.0005,           # 單邊手續費 0.05%
    "BACKTEST_DAYS": 365          # 方式一預設跑過去整整 1 年 (365天) 歷史 K 線對決
}

STATE_FILE = "system_b_state.json"
LIVE_CURVE_FILE = "system_b_live_curve.csv"
BACKTEST_CURVE_FILE = "system_b_backtest_curve.csv"

# ==========================================
# 記憶讀寫模組
# ==========================================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "model_name": CONFIG["MODEL_NAME"],
        "capital": CONFIG["INITIAL_CAPITAL"],
        "in_position": False,
        "pos_type": None,
        "entry_price": 0.0,
        "sl_price": 0.0,
        "tp1_price": 0.0,
        "tp2_price": 0.0,
        "qty": 0.0,
        "margin_used": 0.0,
        "moved_be": False,
        "total_trades": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "last_signal": "WAIT",
        "model_chat": "系統 B 已就緒，50 USDT 初始資金已入帳，等待高勝率共振訊號。"
    }

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ==========================================
# 【第 1 層：黑天鵝與宏觀新聞濾網】
# ==========================================
def check_macro_news():
    keywords = ["FOMC", "CPI", "Powell", "Rate Hike", "War", "Attack", "Hack", "Exploit", "Bankruptcy", "SEC"]
    try:
        res = requests.get("https://cryptocompare.com", timeout=10).json()
        news_list = res.get("Data", [])[:15]
        now_ts = datetime.now(timezone.utc).timestamp()
        for item in news_list:
            if now_ts - item.get("published_on", 0) <= 7200:
                title = item.get("title", "")
                for kw in keywords:
                    if kw.lower() in title.lower():
                        return False, f"高危新聞警報 [{kw}]: {title}"
        return True, "宏觀與鏈上新聞安全"
    except Exception as e:
        return False, f"新聞源連線異常，啟動保護鎖倉 ({e})"

# ==========================================
# 指標與趨勢強度運算 (加入 ADX 過濾震盪假訊號)
# ==========================================
def fetch_ohlcv_days(exchange, symbol, timeframe, days):
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    all_ohlcv = []
    while since < exchange.milliseconds():
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=300)
        if not ohlcv:
            break
        all_ohlcv.extend(ohlcv)
        since = ohlcv[-1] + 1
        time.sleep(0.12)
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    return df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)

def apply_guardian_indicators(df_15m, df_4h):
    df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
    df_4h['ema200'] = df_4h['close'].ewm(span=200, adjust=False).mean()
    df_4h['bull_4h'] = (df_4h['close'] > df_4h['ema50']) & (df_4h['ema50'] > df_4h['ema200'])
    df_4h['bear_4h'] = (df_4h['close'] < df_4h['ema50']) & (df_4h['ema50'] < df_4h['ema200'])

    high, low, close = df_4h['high'], df_4h['low'], df_4h['close']
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm = np.where(plus_dm > minus_dm, plus_dm, 0)
    minus_dm = np.where(minus_dm > plus_dm, minus_dm, 0)
    tr_4h = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr_4h = pd.Series(tr_4h).rolling(14).mean()
    plus_di = 100 * (pd.Series(plus_dm).rolling(14).mean() / atr_4h)
    minus_di = 100 * (pd.Series(minus_dm).rolling(14).mean() / atr_4h)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df_4h['adx'] = dx.rolling(14).mean()

    df = pd.merge_asof(df_15m, df_4h[['timestamp', 'bull_4h', 'bear_4h', 'adx']], on='timestamp', direction='backward')

    df['swing_high'] = df['high'].rolling(12).max().shift(1)
    df['swing_low']  = df['low'].rolling(12).min().shift(1)
    df['vol_ma']     = df['volume'].rolling(20).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss))

    tr = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
    df['atr'] = tr.rolling(14).mean()

    trend_strong = df['adx'] > 20
    vol_ok = df['volume'] > (df['vol_ma'] * 1.25)

    df['long_sig']  = df['bull_4h'] & trend_strong & (df['close'] > df['swing_high']) & vol_ok & (df['rsi'] < 68)
    df['short_sig'] = df['bear_4h'] & trend_strong & (df['close'] < df['swing_low']) & vol_ok & (df['rsi'] > 32)
    return df.dropna().reset_index(drop=True)

# ==========================================
# 【方式二】即時模擬盤對比執行器 (50 U 實戰滾動)
# ==========================================
def run_live_mode(exchange):
    state = load_state()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    news_safe, news_msg = check_macro_news()

    df_4h = fetch_ohlcv_days(exchange, CONFIG["SYMBOL"], "4h", 40)
    df_15m = fetch_ohlcv_days(exchange, CONFIG["SYMBOL"], "15m", 5)
    df = apply_guardian_indicators(df_15m, df_4h)
    latest = df.iloc[-1]
    curr_price = float(latest['close'])
    state["current_price"] = curr_price
    state["last_updated"] = now_str
    state["news_safe"] = news_safe
    state["news_msg"] = news_msg

    if state["in_position"]:
        entry, sl, tp2, qty = state["entry_price"], state["sl_price"], state["tp2_price"], state["qty"]
        if state["pos_type"] == "LONG":
            if not state["moved_be"] and latest['high'] >= state["tp1_price"]:
                state["sl_price"] = round(entry * (1 + CONFIG["FEE_RATE"] * 2), 2)
                state["moved_be"] = True
                state["model_chat"] = f"[{now_str}] 🛡️ 多單已衝破 1.5R ({state['tp1_price']})，止損已推至 {state['sl_price']} 保本，這單立於不敗之地！"
            elif latest['low'] <= sl:
                pnl = (sl - entry) * qty - (entry * qty * CONFIG["FEE_RATE"] * 2)
                state["capital"] = round(state["capital"] + pnl, 2)
                state["in_position"] = False; state["total_trades"] += 1
                if pnl > 0.1: state["win_trades"] += 1
                elif pnl < -0.1: state["loss_trades"] += 1
                state["last_signal"] = "WAIT"
                state["model_chat"] = f"[{now_str}] 多單平倉於 {sl}，本筆盈虧 {pnl:+.2f} U，系統 B 當前總淨值 {state['capital']} U。"
            elif latest['high'] >= tp2:
                pnl = (tp2 - entry) * qty - (entry * qty * CONFIG["FEE_RATE"] * 2)
                state["capital"] = round(state["capital"] + pnl, 2)
                state["in_position"] = False; state["total_trades"] += 1; state["win_trades"] += 1
                state["last_signal"] = "WAIT"
                state["model_chat"] = f"[{now_str}] 🎉 多單精準命中 1:3 止盈 ({tp2})！大賺 {pnl:+.2f} U，系統 B 淨值衝上 {state['capital']} U！"
        else:
            if not state["moved_be"] and latest['low'] <= state["tp1_price"]:
                state["sl_price"] = round(entry * (1 - CONFIG["FEE_RATE"] * 2), 2)
                state["moved_be"] = True
                state["model_chat"] = f"[{now_str}] 🛡️ 空單已跌破 1.5R ({state['tp1_price']})，止損已下移至 {state['sl_price']} 保本！"
            elif latest['high'] >= sl:
                pnl = (entry - sl) * qty - (entry * qty * CONFIG["FEE_RATE"] * 2)
                state["capital"] = round(state["capital"] + pnl, 2)
                state["in_position"] = False; state["total_trades"] += 1
                if pnl > 0.1: state["win_trades"] += 1
                elif pnl < -0.1: state["loss_trades"] += 1
                state["last_signal"] = "WAIT"
                state["model_chat"] = f"[{now_str}] 空單平倉於 {sl}，本筆盈虧 {pnl:+.2f} U，系統 B 當前總淨值 {state['capital']} U。"
            elif latest['low'] <= tp2:
                pnl = (entry - tp2) * qty - (entry * qty * CONFIG["FEE_RATE"] * 2)
                state["capital"] = round(state["capital"] + pnl, 2)
                state["in_position"] = False; state["total_trades"] += 1; state["win_trades"] += 1
                state["last_signal"] = "WAIT"
                state["model_chat"] = f"[{now_str}] 🎉 空單精準命中 1:3 止盈 ({tp2})！大賺 {pnl:+.2f} U，系統 B 淨值衝上 {state['capital']} U！"
    else:
        if not news_safe:
            state["last_signal"] = "LOCKED"
            state["model_chat"] = f"[{now_str}] 🛑 偵測到高危新聞（{news_msg}），系統 B 主動鎖倉避險，保留 {state['capital']} U 現金實力。"
        elif latest['long_sig']:
            sl = round(float(latest['swing_low'] - latest['atr'] * CONFIG["ATR_STOP_MULT"]), 2)
            dist = curr_price - sl
            if dist > 0:
                risk_usd = round(state["capital"] * CONFIG["RISK_PER_TRADE"], 2)
                qty = round(risk_usd / dist, 5)
                margin = round((qty * curr_price) / CONFIG["LEVERAGE"], 2)
                tp1 = round(curr_price + dist * 1.5, 2)
                tp2 = round(curr_price + dist * CONFIG["RR_RATIO"], 2)
                state.update({
                    "in_position": True, "pos_type": "LONG", "last_signal": "BUY",
                    "entry_price": curr_price, "sl_price": sl, "tp1_price": tp1, "tp2_price": tp2,
                    "qty": qty, "margin_used": margin, "moved_be": False,
