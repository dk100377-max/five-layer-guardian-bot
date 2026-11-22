import os, json, time, ccxt, requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CFG = {
    "NAME": "System-B (4H+1H Guardian Pro)", "SYMBOLS": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "CAP": 50.0, "RISK": 0.015, "LEV": 3, "RR": 3.0, "ATR_M": 1.6, "FEE": 0.0005, "DAYS": 1500
}

def send_tg(msg):
    token = os.environ.get("TG_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if token and chat_id:
        try:
            host = "api." + "telegram.org"
            res = requests.post(f"https://{host}/bot{token}/sendMessage", json={"chat_id": chat_id, "text": msg}, timeout=10)
            print("TG 回傳狀態:", res.status_code, res.text)
        except Exception as e:
            print("TG 發送失敗:", e)

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
        time.sleep(0.11)
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
def simulate_range(bdf, init_cap):
    cap, peak, mdd, in_p, is_l, en, sl, tp1, tp2, q, be, reg, r_u = init_cap, init_cap, 0.0, False, True, 0, 0, 0, 0, 0, False, "", 0
    curve, recs = [], []
    for i in range(1, len(bdf)):
        r = bdf.iloc[i]
        ts = pd.to_datetime(r['timestamp'], unit='ms').strftime('%Y-%m-%d %H:%M')
        if in_p:
            if not be and ((r['high'] >= tp1) if is_l else (r['low'] <= tp1)):
                hq = q * 0.5; cap += ((tp1 - en) if is_l else (en - tp1))*hq - en*hq*CFG["FEE"]*2; q -= hq
                sl = en * (1 + CFG["FEE"]*2 if is_l else 1 - CFG["FEE"]*2); be = True
            if (r['low'] <= sl) if is_l else (r['high'] >= sl):
                pnl = ((sl - en) if is_l else (en - sl))*q - en*q*CFG["FEE"]*2; cap += pnl; in_p = False
                recs.append({"regime": reg, "r_mult": pnl / r_u if r_u > 0 else 0})
            elif (r['high'] >= tp2) if is_l else (r['low'] <= tp2):
                pnl = ((tp2 - en) if is_l else (en - tp2))*q - en*q*CFG["FEE"]*2; cap += pnl; in_p = False
                recs.append({"regime": reg, "r_mult": pnl / r_u if r_u > 0 else 0})
            if not in_p:
                peak = max(peak, cap); mdd = max(mdd, (peak - cap)/peak*100)
                curve.append({"timestamp": ts, "account_value": round(cap, 2), "System_B_Balance": round(cap, 2), "signal": "CLOSE"})
        elif r['lsig'] or r['ssig']:
            is_l = bool(r['lsig']); en = r['close']
            sl = (r['sl'] - r['atr']*CFG["ATR_M"]) if is_l else (r['sh'] + r['atr']*CFG["ATR_M"])
            d_px = abs(en - sl)
            if d_px > 0:
                r_u = cap * CFG["RISK"]; q = r_u / d_px
                tp1 = en + (d_px*1.5 if is_l else -d_px*1.5); tp2 = en + (d_px*CFG["RR"] if is_l else -d_px*CFG["RR"])
                in_p, be, reg = True, False, r['regime']
                curve.append({"timestamp": ts, "account_value": round(cap, 2), "System_B_Balance": round(cap, 2), "signal": "BUY" if is_l else "SELL"})
    return cap, mdd, curve, recs, (in_p, is_l, en, sl, tp1, tp2, q, be)

def analyze_coin(ex, sym, nok, cap):
    days = CFG["DAYS"] if sym == "BTC/USDT" else 45
    df = add_ind(get_ohlcv(ex, sym, "1h", days), get_ohlcv(ex, sym, "4h", days))
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
    return df, {"sym": sym, "px": px, "regime": str(lat['regime']), "sig": sig, "sl": p_sl, "tp1": p_tp1, "tp2": p_tp2, "mgn": mgn, "qty": qty, "is_bull": is_bull, "adx": round(float(lat['adx']), 1)}

def main():
    ex = ccxt.okx({'enableRateLimit': True})
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    nok, nmsg = check_news()

    btc_df, btc_info = analyze_coin(ex, "BTC/USDT", nok, CFG["CAP"])
    _, eth_info = analyze_coin(ex, "ETH/USDT", nok, CFG["CAP"])
    _, sol_info = analyze_coin(ex, "SOL/USDT", nok, CFG["CAP"])

    cap_30d, _, curve_30d, _, pos_state = simulate_range(btc_df.tail(720).reset_index(drop=True), CFG["CAP"])
    if not curve_30d:
        curve_30d = [{"timestamp": now_s, "account_value": round(cap_30d, 2), "signal": "WAIT"}]
    pd.DataFrame(curve_30d).to_csv("system_b_live_curve.csv", index=False)

    if not os.path.exists("system_b_backtest_summary.json"):
        cap_4y, mdd_4y, curve_4y, recs_4y, _ = simulate_range(btc_df, CFG["CAP"])
        pd.DataFrame(curve_4y).to_csv("system_b_backtest_curve.csv", index=False)
        rdf = pd.DataFrame(recs_4y)
        def sbox(sub):
            if len(sub) == 0: return {"trades": 0, "win_rate": 0, "expectancy": 0}
            w = sub[sub['r_mult'] > 0.1]; l = sub[sub['r_mult'] < -0.1]; vc = len(w) + len(l)
            wr = round(len(w)/vc*100, 1) if vc > 0 else 0
            aw = w['r_mult'].mean() if len(w) > 0 else 0; al = abs(l['r_mult'].mean()) if len(l) > 0 else 1
            return {"trades": int(len(sub)), "win_rate": wr, "expectancy": round((wr/100)*aw - (1 - wr/100)*al, 2)}
        ov = sbox(rdf)
        summ = {"system": CFG["NAME"], "initial": CFG["CAP"], "final": round(cap_4y, 2), "return_pct": round((cap_4y - CFG["CAP"])/CFG["CAP"]*100, 2),
                "win_rate": ov["win_rate"], "trades": ov["trades"], "expectancy": ov["expectancy"], "max_dd": round(mdd_4y, 2),
                "bull": sbox(rdf[rdf['regime'] == '牛市 (Bull)']), "bear": sbox(rdf[rdf['regime'] == '熊市 (Bear)']), "range": sbox(rdf[rdf['regime'] == '震盪市 (Range)'])}
        with open("system_b_backtest_summary.json", "w", encoding="utf-8") as f:
            json.dump(summ, f, ensure_ascii=False, indent=2)

    st = {
        "model_name": CFG["NAME"], "capital": round(cap_30d, 2), "current_price": btc_info["px"],
        "last_updated": now_s, "news_safe": nok, "news_msg": nmsg, "regime": btc_info["regime"],
        "last_signal": btc_info["sig"], "plan_dir": "LONG" if btc_info["is_bull"] else "SHORT",
        "entry_price": btc_info["px"], "sl_price": btc_info["sl"], "tp1_price": btc_info["tp1"], "tp2_price": btc_info["tp2"],
        "qty": btc_info["qty"], "margin_used": btc_info["mgn"],
        "recommendations": [
            f"BTC 現價 ${btc_info['px']:,.2f} ({btc_info['regime']}) -> 指令：{btc_info['sig']}",
            f"ETH 現價 ${eth_info['px']:,.2f} ({eth_info['regime']}) -> 指令：{eth_info['sig']} | 停損 ${eth_info['sl']} / 止盈 ${eth_info['tp2']}",
            f"SOL 現價 ${sol_info['px']:,.2f} ({sol_info['regime']}) -> 指令：{sol_info['sig']} | 停損 ${sol_info['sl']} / 止盈 ${sol_info['tp2']}"
        ]
    }
    with open("system_b_state.json", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

    lines = [f"🛡️ System-B 三幣種戰情快報 ({now_s})", f"📰 新聞濾網：{'🟢 安全' if nok else '🔴 鎖倉'} ({nmsg})\n"]
    for info in [btc_info, eth_info, sol_info]:
        icon = "🟢" if info["sig"] == "BUY" else ("🔴" if info["sig"] == "SELL" else "⏸️")
        lines.append(f"{icon} {info['sym']} | 現價: ${info['px']:,.2f}\n   狀態: {info['regime']} | 指令: {info['sig']}\n   3x保證金: ${info['mgn']} U | SL: ${info['sl']} | TP2: ${info['tp2']}\n")
    send_tg("\n".join(lines))

if __name__ == "__main__":
    main()
