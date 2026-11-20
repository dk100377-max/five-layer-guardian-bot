import os
import json
import time
import ccxt
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CFG = {
    "NAME": "System-B (Guardian Pro)",
    "SYM": "BTC/USDT",
    "CAP": 50.0,
    "RISK": 0.02,
    "LEV": 3,
    "RR": 3.0,
    "ATR_M": 1.5,
    "FEE": 0.0005,
    "MAX_STREAK": 3,
    "DAYS": 365
}

def load_st():
    if os.path.exists("system_b_state.json"):
        with open("system_b_state.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "model_name": CFG["NAME"], "capital": CFG["CAP"], "in_position": False,
        "pos_type": None, "entry_price": 0.0, "sl_price": 0.0, "tp1_price": 0.0,
        "tp2_price": 0.0, "qty": 0.0, "margin_used": 0.0, "moved_be": False,
        "loss_streak": 0, "total_trades": 0, "win_trades": 0, "loss_trades": 0,
        "last_signal": "WAIT", "model_chat": "系統 B 滿血版已就緒，50U 資金待命中。"
    }

def check_news():
    kws = ["fomc", "cpi", "powell", "rate hike", "war", "attack", "hack", "exploit", "bankruptcy", "sec", "whale dump"]
    try:
        host = "min-api.cryptocompare.com"
        path = "/data/v2/news/?lang=EN"
        data = requests.get(f"https://{host}{path}", timeout=10).json().get("Data", [])[:15]
        now = datetime.now(timezone.utc).timestamp()
        for it in data:
            if now - it.get("published_on", 0) <= 7200:
                t = it.get("title", "").lower()
                for k in kws:
                    if k in t:
                        return False, f"警報 [{k.upper()}]: {it.get('title')}"
        return True, "宏觀與鏈上新聞安全"
    except Exception as e:
        return False, f"新聞源連線異常，啟動保護鎖倉 ({e})"

def get_ohlcv(ex, tf, days):
    since = ex.milliseconds() - days * 86400000
    rows = []
    while since < ex.milliseconds():
        b = ex.fetch_ohlcv(CFG["SYM"], timeframe=tf, since=since, limit=300)
        if not b:
            break
        rows.extend(b)
        since = b[-1][0] + 1
        time.sleep(0.12)
    df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    return df.drop_duplicates('timestamp').sort_values('timestamp').reset_index(drop=True)

def add_ind(d15, d4):
    d4['e50'] = d4['close'].ewm(span=50, adjust=False).mean()
    d4['e200'] = d4['close'].ewm(span=200, adjust=False).mean()
    d4['bull'] = (d4['close'] > d4['e50']) & (d4['e50'] > d4['e200'])
    d4['bear'] = (d4['close'] < d4['e50']) & (d4['e50'] < d4['e200'])
    d4['regime'] = np.select([d4['bull'], d4['bear']], ['牛市 (Bull)', '熊市 (Bear)'], default='震盪市 (Range)')

    h, l, c = d4['high'], d4['low'], d4['close']
    pdm = np.where(h.diff().clip(lower=0) > (-l.diff()).clip(lower=0), h.diff().clip(lower=0), 0)
    mdm = np.where((-l.diff()).clip(lower=0) > h.diff().clip(lower=0), (-l.diff()).clip(lower=0), 0)
    atr4 = pd.Series(np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))).rolling(14).mean()
    pdi = 100 * pd.Series(pdm).rolling(14).mean() / atr4
    mdi = 100 * pd.Series(mdm).rolling(14).mean() / atr4
    d4['adx'] = ((abs(pdi - mdi) / (pdi + mdi)) * 100).rolling(14).mean()

    hh4, ll4 = h.rolling(20).max(), l.rolling(20).min()
    d4['fib_bull_zone'] = c >= (hh4 - (hh4 - ll4) * 0.65)
    d4['fib_bear_zone'] = c <= (ll4 + (hh4 - ll4) * 0.65)

    df = pd.merge_asof(d15, d4[['timestamp', 'bull', 'bear', 'regime', 'adx', 'fib_bull_zone', 'fib_bear_zone']], on='timestamp', direction='backward')

    df['sh'] = df['high'].rolling(12).max().shift(1)
    df['sl'] = df['low'].rolling(12).min().shift(1)
    df['vma'] = df['volume'].rolling(20).mean()
    d = df['close'].diff()
    df['rsi'] = 100 - (100 / (1 + d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))
    df['atr'] = pd.Series(np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))).rolling(14).mean()

    ok = (df['adx'] > 20) & (df['volume'] > df['vma'] * 1.25)
    df['lsig'] = df['bull'] & df['fib_bull_zone'] & ok & (df['close'] > df['sh']) & (df['rsi'] < 68)
    df['ssig'] = df['bear'] & df['fib_bear_zone'] & ok & (df['close'] < df['sl']) & (df['rsi'] > 32)
    return df.dropna().reset_index(drop=True)
def main():
    ex = ccxt.okx({'enableRateLimit': True})
    st = load_st()
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    nok, nmsg = check_news()

    df = add_ind(get_ohlcv(ex, "15m", 5), get_ohlcv(ex, "4h", 40))
    lat = df.iloc[-1]
    px = float(lat['close'])
    st.update({"current_price": px, "last_updated": now_s, "news_safe": nok, "news_msg": nmsg, "regime": str(lat['regime'])})

    if st["in_position"]:
        en, sl, tp1, tp2, qty, is_l = st["entry_price"], st["sl_price"], st["tp1_price"], st["tp2_price"], st["qty"], (st["pos_type"] == "LONG")
        if not st["moved_be"] and ((lat['high'] >= tp1) if is_l else (lat['low'] <= tp1)):
            half_qty = qty * 0.5
            part_pnl = ((tp1 - en) if is_l else (en - tp1)) * half_qty - en * half_qty * CFG["FEE"] * 2
            st["capital"] = round(st["capital"] + part_pnl, 2)
            st["qty"] = round(qty - half_qty, 5)
            st["sl_price"] = round(en * (1 + CFG["FEE"]*2 if is_l else 1 - CFG["FEE"]*2), 2)
            st["moved_be"] = True
            st["model_chat"] = f"[{now_s}] 命中 1.5R ({tp1})！已先平倉一半落袋 {part_pnl:+.2f} U，剩餘倉位止損移至 {st['sl_price']} 零風險博取 1:3！"
        elif (lat['low'] <= sl) if is_l else (lat['high'] >= sl):
            pnl = ((sl - en) if is_l else (en - sl)) * qty - en * qty * CFG["FEE"] * 2
            st["capital"] = round(st["capital"] + pnl, 2)
            st.update({"in_position": False, "last_signal": "WAIT", "total_trades": st["total_trades"] + 1})
            if pnl < -0.1:
                st["loss_trades"] += 1
                st["loss_streak"] = st.get("loss_streak", 0) + 1
            else:
                st["loss_streak"] = 0
            st["model_chat"] = f"[{now_s}] 觸發保護平倉於 {sl}，盈虧 {pnl:+.2f} U，當前淨值 {st['capital']} U。"
        elif (lat['high'] >= tp2) if is_l else (lat['low'] <= tp2):
            pnl = ((tp2 - en) if is_l else (en - tp2)) * qty - en * qty * CFG["FEE"] * 2
            st["capital"] = round(st["capital"] + pnl, 2)
            st.update({"in_position": False, "last_signal": "WAIT", "total_trades": st["total_trades"] + 1, "win_trades": st["win_trades"] + 1, "loss_streak": 0})
            st["model_chat"] = f"[{now_s}] 剩餘倉位命中 1:3 最終止盈 ({tp2})！再賺 {pnl:+.2f} U，總淨值衝上 {st['capital']} U！"
    else:
        if st.get("loss_streak", 0) >= CFG["MAX_STREAK"]:
            st.update({"last_signal": "LOCKED", "model_chat": f"[{now_s}] 已連續虧損 {st['loss_streak']} 筆，觸發第 0 層冷卻熔斷保護，暫停開單。"})
        elif not nok:
            st.update({"last_signal": "LOCKED", "model_chat": f"[{now_s}] 新聞鎖倉避險（{nmsg}），保留 {st['capital']} U 本金。"})
        elif lat['lsig'] or lat['ssig']:
            is_l = bool(lat['lsig'])
            sl = round(float((lat['sl'] - lat['atr']*CFG["ATR_M"]) if is_l else (lat['sh'] + lat['atr']*CFG["ATR_M"])), 2)
            dist = abs(px - sl)
            if dist > 0:
                rusd = round(st["capital"] * CFG["RISK"], 2)
                qty = round(rusd / dist, 5)
                mgn = round((qty * px) / CFG["LEV"], 2)
                tp1 = round(px + (dist*1.5 if is_l else -dist*1.5), 2)
                tp2 = round(px + (dist*CFG["RR"] if is_l else -dist*CFG["RR"]), 2)
                st.update({
                    "in_position": True, "pos_type": "LONG" if is_l else "SHORT", "last_signal": "BUY" if is_l else "SELL",
                    "entry_price": px, "sl_price": sl, "tp1_price": tp1, "tp2_price": tp2, "qty": qty, "margin_used": mgn, "moved_be": False,
                    "model_chat": f"[{now_s}] {'做多' if is_l else '做空'}完整訊號確認！現價 {px}，3x 逐倉投入 {mgn} U 保證金（{qty} BTC），停損 {sl}（風險 {rusd} U），1.5R 半倉止盈保本 {tp1}，最終止盈 {tp2}。"
                })
        else:
            st.update({"last_signal": "WAIT", "model_chat": f"[{now_s}] 當前【{st['regime']}】ADX={lat['adx']:.1f}，尚未出現五層共振突破，空手等待（淨值 {st['capital']} U）。"})

    with open("system_b_state.json", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    pd.DataFrame([{"timestamp": now_s, "system": CFG["NAME"], "account_value": st["capital"], "signal": st["last_signal"]}]).to_csv(
        "system_b_live_curve.csv", mode='a', header=not os.path.exists("system_b_live_curve.csv"), index=False)
    print("即時模擬執行完成：", st["model_chat"])

    if not os.path.exists("system_b_backtest_summary.json"):
        print("正在下載過去 365 天歷史 K 線進行牛熊全週期壓力測試...")
        bdf = add_ind(get_ohlcv(ex, "15m", CFG["DAYS"]), get_ohlcv(ex, "4h", CFG["DAYS"]))
        cap, peak, mdd, in_p, is_l, en, sl, tp1, tp2, qty, be, reg, rusd = CFG["CAP"], CFG["CAP"], 0.0, False, True, 0, 0, 0, 0, 0, False, "", 0
        curve, recs = [], []
        for i in range(1, len(bdf)):
            r = bdf.iloc[i]
            if in_p:
                if not be and ((r['high'] >= tp1) if is_l else (r['low'] <= tp1)):
                    hq = qty * 0.5
                    cap += ((tp1 - en) if is_l else (en - tp1))*hq - en*hq*CFG["FEE"]*2
                    qty -= hq
                    sl = en * (1 + CFG["FEE"]*2 if is_l else 1 - CFG["FEE"]*2)
                    be = True
                if (r['low'] <= sl) if is_l else (r['high'] >= sl):
                    pnl = ((sl - en) if is_l else (en - sl))*qty - en*qty*CFG["FEE"]*2
                    cap += pnl; in_p = False
                    recs.append({"regime": reg, "r_mult": pnl / rusd if rusd > 0 else 0})
                elif (r['high'] >= tp2) if is_l else (r['low'] <= tp2):
                    pnl = ((tp2 - en) if is_l else (en - tp2))*qty - en*qty*CFG["FEE"]*2
                    cap += pnl; in_p = False
                    recs.append({"regime": reg, "r_mult": pnl / rusd if rusd > 0 else 0})
                if not in_p:
                    peak = max(peak, cap); mdd = max(mdd, (peak - cap)/peak*100)
                    curve.append({"timestamp": pd.to_datetime(r['timestamp'], unit='ms').strftime('%Y-%m-%d %H:%M'), "System_B_Balance": round(cap, 2)})
            elif r['lsig'] or r['ssig']:
                is_l = bool(r['lsig']); en = r['close']
                sl = (r['sl'] - r['atr']*CFG["ATR_M"]) if is_l else (r['sh'] + r['atr']*CFG["ATR_M"])
                dist = abs(en - sl)
                if dist > 0:
                    rusd = cap * CFG["RISK"]
                    qty = rusd / dist
                    tp1 = en + (dist*1.5 if is_l else -dist*1.5)
                    tp2 = en + (dist*CFG["RR"] if is_l else -dist*CFG["RR"])
                    in_p, be, reg = True, False, r['regime']

        pd.DataFrame(curve).to_csv("system_b_backtest_curve.csv", index=False)
        rdf = pd.DataFrame(recs)
        def stat_box(sub):
            if len(sub) == 0: return {"trades": 0, "win_rate": 0, "expectancy": 0}
            w = sub[sub['r_mult'] > 0.1]; l = sub[sub['r_mult'] < -0.1]
            vc = len(w) + len(l)
            wr = round(len(w)/vc*100, 1) if vc > 0 else 0
            aw = w['r_mult'].mean() if len(w) > 0 else 0
            al = abs(l['r_mult'].mean()) if len(l) > 0 else 1
            return {"trades": int(len(sub)), "win_rate": wr, "expectancy": round((wr/100)*aw - (1 - wr/100)*al, 2)}

        ov = stat_box(rdf)
        summ = {
            "system": CFG["NAME"], "initial": CFG["CAP"], "final": round(cap, 2),
            "return_pct": round((cap - CFG["CAP"])/CFG["CAP"]*100, 2),
            "win_rate": ov["win_rate"], "trades": ov["trades"], "expectancy": ov["expectancy"], "max_dd": round(mdd, 2),
            "bull": stat_box(rdf[rdf['regime'] == '牛市 (Bull)']),
            "bear": stat_box(rdf[rdf['regime'] == '熊市 (Bear)']),
            "range": stat_box(rdf[rdf['regime'] == '震盪市 (Range)'])
        }
        with open("system_b_backtest_summary.json", "w", encoding="utf-8") as f:
            json.dump(summ, f, ensure_ascii=False, indent=2)
        print("系統 B 滿血版一年期競賽成績單：", json.dumps(summ, ensure_ascii=False))

if __name__ == "__main__":
    main()
