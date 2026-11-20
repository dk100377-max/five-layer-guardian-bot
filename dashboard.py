import os, json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="System-B (4H+1H) 智能交易戰情室", page_icon="🛡️", layout="wide")

state = json.load(open("system_b_state.json", "r", encoding="utf-8")) if os.path.exists("system_b_state.json") else None
bt_summary = json.load(open("system_b_backtest_summary.json", "r", encoding="utf-8")) if os.path.exists("system_b_backtest_summary.json") else None

if not state:
    st.warning("⏳ 請先到 GitHub Actions 點擊 `Run workflow` 執行一次運算。")
    st.stop()

st.title("📊 System-B (4H + 1H Guardian Pro) 智能交易分析戰情室")
t1, t2, t3, t4 = st.columns(4)
t1.metric("Current Price (當前市價)", f"${state.get('current_price', 0):,.2f}")
cap = state.get("capital", 50.0)
t2.metric("即時模擬盤帳戶淨值 (初始 50U)", f"${cap:.2f} U", f"{round((cap-50)/50*100, 2):+.2f}%")
t3.metric("市場趨勢與新聞濾網", f"{state.get('regime', '-')} | {'🟢 安全' if state.get('news_safe') else '🔴 鎖倉'}")
t4.metric("最後更新時間 (每小時整點巡檢)", state.get("last_updated", "-"))

st.divider()

sig = state.get("last_signal", "WAIT")
is_long = (state.get("plan_dir", "LONG") == "LONG")
en = state.get("entry_price", 0.0)
sl = state.get("sl_price", 0.0)
tp1 = state.get("tp1_price", 0.0)
tp2 = state.get("tp2_price", 0.0)

c_left, c_right = st.columns([1.3, 1])
with c_left:
    st.subheader("Pattern Analysis & 交易決策指令")
    if sig == "BUY":
        st.success(f"### 🟢 BUY NOW (立即進場做多) | 進場價: ${en:,.2f}")
    elif sig == "SELL":
        st.error(f"### 🔴 SELL NOW (立即進場做空) | 進場價: ${en:,.2f}")
    elif sig == "LOCKED":
        st.warning("### 🛑 LOCKED (高危新聞/熔斷保護，禁止下單)")
    else:
        st.info(f"### ⏸️ WAIT (等待 1H 訊號確認，暫不進場) | 預估觀察價: ${en:,.2f}")

with c_right:
    st.subheader("Risk Management (倉位與槓桿精算)")
    r1, r2, r3 = st.columns(3)
    r1.metric("單筆最大風險", "1.50%", f"-${round(cap*0.015, 2)} U")
    r2.metric("建議槓桿 (逐倉)", "3x Isolated", f"保證金 ${state.get('margin_used', 0)} U")
    r3.metric("目標盈虧比 (R:R)", "3.00 : 1", f"買入 {state.get('qty', 0)} BTC")
st.markdown("#### 📍 視覺化進出場價格軌道圖（一秒看懂止損與分批止盈位置）")
if en > 0:
    sl_pct = round(abs(sl - en) / en * 100, 2)
    tp1_pct = round(abs(tp1 - en) / en * 100, 2)
    tp2_pct = round(abs(tp2 - en) / en * 100, 2)

    if is_long:
        track_html = f"""
        <div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; padding:18px; border-radius:12px; border:1px solid #e2e8f0; margin-bottom:15px;">
            <div style="text-align:center;"><span style="background:#ef4444; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">SL 停損</span><br><b style="color:#dc2626; font-size:16px;">${sl:,.2f}</b><br><small>-{sl_pct}%</small></div>
            <div style="color:#94a3b8; font-size:20px;">◀━━━</div>
            <div style="text-align:center;"><span style="background:#3b82f6; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">Entry 進場</span><br><b style="color:#1d4ed8; font-size:16px;">${en:,.2f}</b><br><small>基準點</small></div>
            <div style="color:#22c55e; font-size:20px;">━━━▶</div>
            <div style="text-align:center;"><span style="background:#10b981; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">TP1 半倉保本</span><br><b style="color:#059669; font-size:16px;">${tp1:,.2f}</b><br><small>+{tp1_pct}% (1.5R)</small></div>
            <div style="color:#22c55e; font-size:20px;">━━━▶</div>
            <div style="text-align:center;"><span style="background:#059669; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">TP2 最終止盈</span><br><b style="color:#047857; font-size:16px;">${tp2:,.2f}</b><br><small>+{tp2_pct}% (3.0R)</small></div>
        </div>
        """
    else:
        track_html = f"""
        <div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; padding:18px; border-radius:12px; border:1px solid #e2e8f0; margin-bottom:15px;">
            <div style="text-align:center;"><span style="background:#059669; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">TP2 最終止盈</span><br><b style="color:#047857; font-size:16px;">${tp2:,.2f}</b><br><small>-{tp2_pct}% (3.0R)</small></div>
            <div style="color:#22c55e; font-size:20px;">◀━━━</div>
            <div style="text-align:center;"><span style="background:#10b981; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">TP1 半倉保本</span><br><b style="color:#059669; font-size:16px;">${tp1:,.2f}</b><br><small>-{tp1_pct}% (1.5R)</small></div>
            <div style="color:#22c55e; font-size:20px;">◀━━━</div>
            <div style="text-align:center;"><span style="background:#3b82f6; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">Entry 進場</span><br><b style="color:#1d4ed8; font-size:16px;">${en:,.2f}</b><br><small>基準點</small></div>
            <div style="color:#94a3b8; font-size:20px;">━━━▶</div>
            <div style="text-align:center;"><span style="background:#ef4444; color:white; padding:4px 10px; border-radius:6px; font-weight:bold;">SL 停損</span><br><b style="color:#dc2626; font-size:16px;">${sl:,.2f}</b><br><small>+{sl_pct}%</small></div>
        </div>
        """
    st.markdown(track_html, unsafe_allow_html=True)

    k1, k2, k3 = st.columns(3)
    k1.error(f"**Stop Loss (SL 停損價)**\n\n### ${sl:,.2f}\n虧損幅度: {sl_pct}% (最多虧 ${round(cap*0.015, 2)} U)")
    k2.success(f"**Take Profit 1 (TP1 保本點)**\n\n### ${tp1:,.2f}\n獲利幅度: {tp1_pct}% (平半倉＋移保本)")
    k3.success(f"**Take Profit 2 (TP2 目標價)**\n\n### ${tp2:,.2f}\n獲利幅度: {tp2_pct}% (完整 1:3 盈虧比)")

st.markdown("#### 💡 Trade Recommendations (系統 B 操作建議)")
for rec in state.get("recommendations", ["等待系統更新..."]):
    st.markdown(f"- **{rec}**")

st.divider()

tab1, tab2 = st.tabs(["📊 過去 4.1 年 (1,500天) 跨牛熊全週期回測成績單", "⚔️ 即時模擬盤資金曲線 (每小時自動記帳)"])
with tab1:
    if bt_summary and os.path.exists("system_b_backtest_curve.csv"):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("4.1年後最終淨值 (初始 50U)", f"${bt_summary.get('final', 50)} U", f"{bt_summary.get('return_pct', 0):+.2f}%")
        m2.metric("真實勝率 / 期望值", f"{bt_summary.get('win_rate', 0)}%", f"{bt_summary.get('expectancy', 0):+.2f}R")
        m3.metric("總交易次數", f"{bt_summary.get('trades', 0)} 筆")
        m4.metric("歷史最大回撤 (MDD)", f"{bt_summary.get('max_dd', 0)}%", "畢業線 < 15%", delta_color="inverse")

        r1, r2, r3 = st.columns(3)
        bull, bear, rng = bt_summary.get("bull", {}), bt_summary.get("bear", {}), bt_summary.get("range", {})
        r1.metric("🐂 牛市 (Bull)", f"勝率 {bull.get('win_rate', 0)}%", f"期望值 {bull.get('expectancy', 0):+.2f}R ({bull.get('trades', 0)}筆)")
        r2.metric("🐻 熊市 (Bear)", f"勝率 {bear.get('win_rate', 0)}%", f"期望值 {bear.get('expectancy', 0):+.2f}R ({bear.get('trades', 0)}筆)")
        r3.metric("🦀 震盪市 (Range)", f"勝率 {rng.get('win_rate', 0)}%", f"期望值 {rng.get('expectancy', 0):+.2f}R ({rng.get('trades', 0)}筆)")

        st.line_chart(pd.read_csv("system_b_backtest_curve.csv").set_index("timestamp")["System_B_Balance"], height=320)
with tab2:
    if os.path.exists("system_b_live_curve.csv"):
        ldf = pd.read_csv("system_b_live_curve.csv")
        st.line_chart(ldf.set_index("timestamp")["account_value"], height=280)
        st.dataframe(ldf.tail(15), use_container_width=True)
