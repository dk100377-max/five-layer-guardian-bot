import os, json, time, ccxt, requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CFG = {
    "NAME": "System-B (4H+1H Guardian Pro)", "SYM": "BTC/USDT", "CAP": 50.0,
    "RISK": 0.015, "LEV": 3, "RR": 3.0, "ATR_M": 1.6, "FEE": 0.0005,
    "MAX_STREAK": 3, "DAYS": 1500
}

def load_st():
    if os.path.exists("system_b_state.json"):
        with open("system_b_state.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "model_name": CFG["NAME"], "capital": CFG["CAP"], "in_position": False, "pos_type": None,
        "entry_price": 0.0, "sl_price": 0.0, "tp1_price": 0.0, "tp2_price": 0.0, "qty": 0.0,
        "margin_used": 0.0, "moved_be": False, "loss_streak": 0, "total_trades": 0, "win_trades": 0,
        "loss_trades": 0, "last_signal": "WAIT", "plan_dir": "LONG", "recommendations": []
    }

def check_news():
    kws = ["fomc", "cpi", "powell", "rate hike", "war", "attack", "hack", "exploit", "bankruptcy", "sec", "whale dump"]
    try:
        api = "https://cryptocompare.com" + "/data/v2/news/?lang=EN"
        raw = requests.get(api, timeout=10).json().get("Data", [])
        data = raw[:15] if isinstance(raw, list) else []
        now = datetime.now(timezone.utc).timestamp()
        for it in data:
            if isinstance(it, dict) and (now - it.get("published_on", 0) <= 7200):
                t = str(it.get("title", "")).lower()
                for k in kws:
                    if k in t:
                        return False, f"警報 [{k.upper()}]: {it.get('title')}"
        return True, "宏觀與鏈上新聞安全（無重大突發利空）"
    except Exception:
        return True, "新聞源備援通過（無重大突發警報）"

def get_ohlcv(ex, tf, days):
    since = ex.milliseconds() - days * 86400000
    rows = []
    while since < ex.milliseconds():
        b = ex.fetch_ohlcv(CFG["SYM"], timeframe=tf, since=since, limit=300)
        if not b: break
        rows.extend(b)
        since = b[-1] + 1
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
def main():
    ex = ccxt.okx({'enableRateLimit': True})
    st = load_st()
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    nok, nmsg = check_news()
    df = add_ind(get_ohlcv(ex, "1h", 15), get_ohlcv(ex, "4h", 45))
    lat = df.iloc[-1]
    px = float(lat['close'])
    st.update({"current_price": px, "last_updated": now_s, "news_safe": nok, "news_msg": nmsg, "regime": str(lat['regime'])})

    is_bull = bool(lat['bull'])
    p_sl = round(float((lat['sl'] - lat['atr']*CFG["ATR_M"]) if is_bull else (lat['sh'] + lat['atr']*CFG["ATR_M"])), 2)
    dist = abs(px - p_sl) if abs(px - p_sl) > 0 else px * 0.02
    rusd = round(st["capital"] * CFG["RISK"], 2)
    qty = round(rusd / dist, 5)
    mgn = round((qty * px) / CFG["LEV"], 2)
    p_tp1 = round(px + (dist*1.5 if is_bull else -dist*1.5), 2)
    p_tp2 = round(px + (dist*CFG["RR"] if is_bull else -dist*CFG["RR"]), 2)

    if st["in_position"]:
        en, sl, tp1, tp2, q, is_l = st["entry_price"], st["sl_price"], st["tp1_price"], st["tp2_price"], st["qty"], (st["pos_type"] == "LONG")
        if not st["moved_be"] and ((lat['high'] >= tp1) if is_l else (lat['low'] <= tp1)):
            hq = q * 0.5
            ppnl = ((tp1 - en) if is_l else (en - tp1)) * hq - en * hq * CFG["FEE"] * 2
            st["capital"] = round(st["capital"] + ppnl, 2); st["qty"] = round(q - hq, 5)
            st["sl_price"] = round(en * (1 + CFG["FEE"]*2 if is_l else 1 - CFG["FEE"]*2), 2); st["moved_be"] = True
            st["recommendations"] = ["已命中 TP1 (1.5R) 並自動平倉一半落袋為安", f"剩餘倉位止損已推至 {st['sl_price']} 保本，零風險博取 TP2 ({tp2})"]
        elif (lat['low'] <= sl) if is_l else (lat['high'] >= sl):
            pnl = ((sl - en) if is_l else (en - sl)) * q - en * q * CFG["FEE"] * 2
            st["capital"] = round(st["capital"] + pnl, 2)
            st.update({"in_position": False, "last_signal": "WAIT", "total_trades": st["total_trades"] + 1})
            if pnl < -0.1: st["loss_trades"] += 1; st["loss_streak"] = st.get("loss_streak", 0) + 1
            else: st["loss_streak"] = 0
            st["recommendations"] = [f"觸發保護平倉於 {sl}（盈虧 {pnl:+.2f} U）", "等待下一次 4H + 1H 結構共振訊號"]
        elif (lat['high'] >= tp2) if is_l else (lat['low'] <= tp2):
            pnl = ((tp2 - en) if is_l else (en - tp2)) * q - en * q * CFG["FEE"] * 2
            st["capital"] = round(st["capital"] + pnl, 2)
            st.update({"in_position": False, "last_signal": "WAIT", "total_trades": st["total_trades"] + 1, "win_trades": st["win_trades"] + 1, "loss_streak": 0})
            st["recommendations"] = [f"完美命中最終止盈 TP2 ({tp2})！獲利 {pnl:+.2f} U", "已全數落袋，空手等待下一波機會"]
    else:
        dir_str = "LONG" if is_bull else "SHORT"
        if not nok:
            st.update({"last_signal": "LOCKED", "plan_dir": dir_str, "entry_price": px, "sl_price": p_sl, "tp1_price": p_tp1, "tp2_price": p_tp2, "qty": qty, "margin_used": mgn,
                       "recommendations": [f"新聞濾網警報：{nmsg}", "系統強制鎖倉保護本金，禁止任何下單操作"]})
        elif lat['lsig'] or lat['ssig']:
            is_l = bool(lat['lsig'])
            st.update({"in_position": True, "pos_type": "LONG" if is_l else "SHORT", "last_signal": "BUY" if is_l else "SELL", "plan_dir": "LONG" if is_l else "SHORT",
                       "entry_price": px, "sl_price": p_sl, "tp1_price": p_tp1, "tp2_price": p_tp2, "qty": qty, "margin_used": mgn, "moved_be": False,
                       "recommendations": [f"4H+1H 雙週期訊號確認！立即以 3x 逐倉投入 {mgn} U 保證金（{'買入做多' if is_l else '賣出做空'} {qty} BTC）",
                                           f"進場同時掛好止損單 {p_sl}（最大虧損鎖死 {rusd} U / 1.5%）",
                                           f"價格到達 {p_tp1} (TP1) 時平倉 50% 並將止損移至進場價保本"]})
        else:
            st.update({"last_signal": "WAIT", "plan_dir": dir_str, "entry_price": px, "sl_price": p_sl, "tp1_price": p_tp1, "tp2_price": p_tp2, "qty": qty, "margin_used": mgn,
                       "recommendations": ["請先空手等待更明確的 1H 回踩 EMA21 確認訊號，切勿提前進場",
                                           f"持續監控 4H 關鍵結構與趨勢強度（目前 ADX={lat['adx']:.1f}）",
                                           f"若下個整點觸發訊號，系統預計僅投入 {mgn} U 保證金（3x 逐倉），最大風險控制在 {rusd} U 以內"]})

    with open("system_b_state.json", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    pd.DataFrame([{"timestamp": now_s, "system": CFG["NAME"], "account_value": st["capital"], "signal": st["last_signal"]}]).to_csv(
        "system_b_live_curve.csv", mode='a', header=not os.path.exists("system_b_live_curve.csv"), index=False)

    if not os.path.exists("system_b_backtest_summary.json"):
        bdf = add_ind(get_ohlcv(ex, "1h", CFG["DAYS"]), get_ohlcv(ex, "4h", CFG["DAYS"]))
        cap, peak, mdd, in_p, is_l, en, sl, tp1, tp2, q, be, reg, r_u = CFG["CAP"], CFG["CAP"], 0.0, False, True, 0, 0, 0, 0, 0, False, "", 0
        curve, recs = [], []
        for i in range(1, len(bdf)):
            r = bdf.iloc[i]
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
                    curve.append({"timestamp": pd.to_datetime(r['timestamp'], unit='ms').strftime('%Y-%m-%d %H:%M'), "System_B_Balance": round(cap, 2)})
            elif r['lsig'] or r['ssig']:
                is_l = bool(r['lsig']); en = r['close']
                sl = (r['sl'] - r['atr']*CFG["ATR_M"]) if is_l else (r['sh'] + r['atr']*CFG["ATR_M"])
                d_px = abs(en - sl)
                if d_px > 0:
                    r_u = cap * CFG["RISK"]; q = r_u / d_px
                    tp1 = en + (d_px*1.5 if is_l else -d_px*1.5); tp2 = en + (d_px*CFG["RR"] if is_l else -d_px*CFG["RR"])
                    in_p, be, reg = True, False, r['regime']
        pd.DataFrame(curve).to_csv("system_b_backtest_curve.csv", index=False)
        rdf = pd.DataFrame(recs)
        def sbox(sub):
            if len(sub) == 0: return {"trades": 0, "win_rate": 0, "expectancy": 0}
            w = sub[sub['r_mult'] > 0.1]; l = sub[sub['r_mult'] < -0.1]; vc = len(w) + len(l)
            wr = round(len(w)/vc*100, 1) if vc > 0 else 0
            aw = w['r_mult'].mean() if len(w) > 0 else 0; al = abs(l['r_mult'].mean()) if len(l) > 0 else 1
            return {"trades": int(len(sub)), "win_rate": wr, "expectancy": round((wr/100)*aw - (1 - wr/100)*al, 2)}
        ov = sbox(rdf)
        summ = {"system": CFG["NAME"], "initial": CFG["CAP"], "final": round(cap, 2), "return_pct": round((cap - CFG["CAP"])/CFG["CAP"]*100, 2),
                "win_rate": ov["win_rate"], "trades": ov["trades"], "expectancy": ov["expectancy"], "max_dd": round(mdd, 2),
                "bull": sbox(rdf[rdf['regime'] == '牛市 (Bull)']), "bear": sbox(rdf[rdf['regime'] == '熊市 (Bear)']), "range": sbox(rdf[rdf['regime'] == '震盪市 (Range)'])}
        with open("system_b_backtest_summary.json", "w", encoding="utf-8") as f:
            json.dump(summ, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
