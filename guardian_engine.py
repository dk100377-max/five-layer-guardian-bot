import os, json, time, ccxt, requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CFG = {
    "NAME": "System-B (10-Coin Arena Pro)",
    "SYMBOLS": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "SUI/USDT", "LINK/USDT"],
    "CAP": 50.0, "RISK": 0.02, "LEV": 3, "RR": 3.0, "ATR_M": 1.6, "FEE": 0.0005
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
def run_engine():
    ex = ccxt.okx({'enableRateLimit': True})
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    nok, nmsg = check_news()
    arena = load_arena_state()
    cap = arena["capital"]

    candidates = []
    btc_info = None

    for sym in CFG["SYMBOLS"]:
        try:
            df = add_ind(get_ohlcv(ex, sym, "1h", 30), get_ohlcv(ex, sym, "4h", 30))
            lat = df.iloc[-1]
            px = float(lat['close'])
            is_bull = bool(lat['bull'])
            p_sl = round(float((lat['sl'] - lat['atr']*CFG["ATR_M"]) if is_bull else (lat['sh'] + lat['atr']*CFG["ATR_M"])), 4)
            dist = abs(px - p_sl) if abs(px - p_sl) > 0 else px * 0.02
            rusd = round(cap * CFG["RISK"], 2)
            qty = round(rusd / dist, 4)
            mgn = round((qty * px) / CFG["LEV"], 2)
            p_tp1 = round(px + (dist*1.5 if is_bull else -dist*1.5), 4)
            p_tp2 = round(px + (dist*CFG["RR"] if is_bull else -dist*CFG["RR"]), 4)
            sig = "LOCKED" if not nok else ("BUY" if lat['lsig'] else ("SELL" if lat['ssig'] else "WAIT"))

            if sym in arena["positions"]:
                pos = arena["positions"][sym]
                is_l = (pos["dir"] == "BUY")
                if not pos.get("moved_be") and ((lat['high'] >= pos["tp1"]) if is_l else (lat['low'] <= pos["tp1"])):
                    hq = pos["qty"] * 0.5
                    ppnl = ((pos["tp1"] - pos["entry"]) if is_l else (pos["entry"] - pos["tp1"])) * hq - pos["entry"]*hq*CFG["FEE"]*2
                    cap = round(cap + ppnl, 2); pos["qty"] -= hq; pos["sl"] = pos["entry"]; pos["moved_be"] = True
                    arena["history"].append(f"[{now_s}] {sym} 命中 TP1 半倉落袋 {ppnl:+.2f} U")
                elif (lat['low'] <= pos["sl"]) if is_l else (lat['high'] >= pos["sl"]):
                    pnl = ((pos["sl"] - pos["entry"]) if is_l else (pos["entry"] - pos["sl"])) * pos["qty"] - pos["entry"]*pos["qty"]*CFG["FEE"]*2
                    cap = round(cap + pnl, 2); del arena["positions"][sym]
                    arena["history"].append(f"[{now_s}] {sym} 觸發保護平倉 {pnl:+.2f} U")
                elif (lat['high'] >= pos["tp2"]) if is_l else (lat['low'] <= pos["tp2"]):
                    pnl = ((pos["tp2"] - pos["entry"]) if is_l else (pos["entry"] - pos["tp2"])) * pos["qty"] - pos["entry"]*pos["qty"]*CFG["FEE"]*2
                    cap = round(cap + pnl, 2); del arena["positions"][sym]
                    arena["history"].append(f"[{now_s}] {sym} 命中 1:3 止盈大賺 {pnl:+.2f} U")

            info = {"sym": sym, "px": px, "regime": str(lat['regime']), "sig": sig, "sl": p_sl, "tp1": p_tp1, "tp2": p_tp2, "mgn": mgn, "qty": qty, "is_bull": is_bull, "adx": float(lat['adx'])}
            if sym == "BTC/USDT": btc_info = info
            if sig in ["BUY", "SELL"] and sym not in arena["positions"] and len(arena["positions"]) < 2:
                candidates.append(info)
        except Exception as e:
            print(f"{sym} 略過:", e)

    candidates.sort(key=lambda x: x["adx"], reverse=True)
    new_orders = []
    for best in candidates[:2 - len(arena["positions"])]:
        arena["positions"][best["sym"]] = {"dir": best["sig"], "entry": best["px"], "sl": best["sl"], "tp1": best["tp1"], "tp2": best["tp2"], "qty": best["qty"], "mgn": best["mgn"], "moved_be": False}
        new_orders.append(best)
        arena["history"].append(f"[{now_s}] 開單 {best['sig']} {best['sym']} @ {best['px']}")

    arena["capital"] = cap
    with open("arena_14d_state.json", "w", encoding="utf-8") as f:
        json.dump(arena, f, ensure_ascii=False, indent=2)

    first_sig = new_orders[0]["sig"] if new_orders else "HOLD"
    pd.DataFrame([{"timestamp": now_s, "system": CFG["NAME"], "account_value": cap, "signal": first_sig}]).to_csv(
        "system_b_live_curve.csv", mode='a', header=not os.path.exists("system_b_live_curve.csv"), index=False)

    top = new_orders[0] if new_orders else btc_info
    if top:
        st = {
            "model_name": CFG["NAME"], "capital": cap, "current_price": top["px"], "last_updated": now_s,
            "news_safe": nok, "news_msg": nmsg, "regime": top["regime"], "last_signal": top["sig"],
            "plan_dir": "LONG" if top["is_bull"] else "SHORT", "entry_price": top["px"], "sl_price": top["sl"],
            "tp1_price": top["tp1"], "tp2_price": top["tp2"], "qty": top["qty"], "margin_used": top["mgn"],
            "recommendations": [f"14天競賽當前淨值：${cap:.2f} U (初始 50U) | 持倉數：{len(arena['positions'])}/2"] + (arena["history"][-3:] if arena["history"] else ["全市場 10 大幣種掃描中，等待高勝率共振訊號"])
        }
        with open("system_b_state.json", "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)

    ret_pct = round((cap - 50.0) / 50.0 * 100, 2)
    if not nok:
        msg = f"🛑 14天競賽戰報 ({now_s})\n目前淨值：${cap:.2f} U ({ret_pct:+.2f}%)\n結論：【全部禁止下單】\n原因：{nmsg}"
    elif new_orders:
        lines = [f"🚨 【14天競賽進場通知】({now_s})", f"當前淨值：${cap:.2f} U ({ret_pct:+.2f}%)\n"]
        for o in new_orders:
            act = "做多 (BUY)" if o["sig"] == "BUY" else "做空 (SELL)"
            lines.append(f"🔥 精選標的：{o['sym']} -> 立即{act}\n• 進場價：${o['px']}\n• 3x保證金：${o['mgn']} U\n• 停損價 (SL)：${o['sl']}\n• 止盈價 (TP2)：${o['tp2']}\n")
        msg = "\n".join(lines)
    else:
        pos_txt = ", ".join([f"{k}({v['dir']})" for k, v in arena["positions"].items()]) if arena["positions"] else "空手觀望中"
        msg = f"🛡️ 14天競賽巡檢結論 ({now_s})\n當前淨值：${cap:.2f} U ({ret_pct:+.2f}%)\n持倉狀態：{pos_txt}\n結論：掃描 10 大主流幣後，目前無新進場訊號（嚴格保護本金，不亂開單）。"
    send_tg(msg)

if __name__ == "__main__":
    try:
        run_engine()
    except Exception as err:
        send_tg(f"⚠️ 系統 B 執行遇到錯誤：{err}")
        raise
