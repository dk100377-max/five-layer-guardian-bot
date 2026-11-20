import os
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="五層小資金交易決策戰情室", page_icon="🛡️", layout="wide")

st.title("🛡️ 五層小資金交易決策與雙系統對決戰情室")
st.caption("策略核心：4H 趨勢與 ADX 強度過濾 ＋ 15m 放量結構突破 ＋ 黑天鵝新聞熔斷 ＋ 1.5R 半倉保本 ＋ 1:3 盈虧比")

state = None
if os.path.exists("system_b_state.json"):
    with open("system_b_state.json", "r", encoding="utf-8") as f:
        state = json.load(f)

bt_summary = None
if os.path.exists("system_b_backtest_summary.json"):
    with open("system_b_backtest_summary.json", "r", encoding="utf-8") as f:
        bt_summary = json.load(f)

if not state:
    st.warning("⏳ 系統尚未執行首次雲端運算！請先到 GitHub 倉庫上方的 `Actions` 分頁，點擊 `Run workflow` 啟動第一次掃描。")
    st.stop()

# 第一區：頂部新聞安全與即時狀態列
col_top1, col_top2, col_top3, col_top4 = st.columns(4)
with col_top1:
    st.metric("BTC 當前價格", f"${state.get('current_price', 0):,.2f}")
with col_top2:
    cap = state.get("capital", 50.0)
    ret = round((cap - 50.0) / 50.0 * 100, 2)
    st.metric("系統 B 當前淨值 (初始 50U)", f"${cap:.2f} U", f"{ret:+.2f}%")
with col_top3:
    news_status = "🟢 新聞環境安全" if state.get("news_safe", True) else "🔴 高危新聞鎖倉中"
    st.metric("第 1 層時勢濾網", news_status)
with col_top4:
    st.metric("最後雲端巡檢時間", state.get("last_updated", "-"))

st.divider()

# 第二區：極度直觀「現在該怎麼做」交易指令卡片
st.subheader("🎯 即時交易決策指令（看這張卡操作即可）")

sig = state.get("last_signal", "WAIT")
c1, c2 = st.columns([1.2, 1.8])

with c1:
    if sig == "BUY":
        st.success("### 🟢 訊號確認：現在進場做多 (BUY)")
    elif sig == "SELL":
        st.error("### 🔴 訊號確認：現在進場做空 (SELL)")
    elif sig == "LOCKED":
        st.warning("### 🛑 風控鎖定：新聞/熔斷保護，禁止下單")
    else:
        st.info("### ⏸️ 訊號未確定：空手等待 (WAIT)")

    st.markdown(f"""
    * **當前市場狀態**：`{state.get('regime', '偵測中')}`
    * **建議槓桿模式**：`3 倍逐倉 (3x Isolated)`
    * **建議投入保證金**：**`{state.get('margin_used', 0)} USDT`** *(其餘資金留作安全墊)*
    * **建議買入數量**：**`{state.get('qty', 0)} BTC`**
    """)

with c2:
    st.markdown("#### 📍 關鍵買賣與風控價格軸")
    p_col1, p_col2, p_col3, p_col4 = st.columns(4)
    p_col1.metric("建議進場價 (Entry)", f"${state.get('entry_price', 0):,.2f}")
    p_col2.metric("❌ 防插針停損 (SL)", f"${state.get('sl_price', 0):,.2f}", "-2% 總資金上限", delta_color="inverse")
    p_col3.metric("🛡️ 半倉保本目標 (TP1)", f"${state.get('tp1_price', 0):,.2f}", "到價平半倉＋移保本")
    p_col4.metric("💰 最終止盈目標 (TP2)", f"${state.get('tp2_price', 0):,.2f}", "1:3 盈虧比")

    st.info(f"**🤖 系統 B 思考日誌 (ModelChat)**：\n\n{state.get('model_chat', '')}")

st.divider()

# 第三區：雙系統對決戰場
tab1, tab2 = st.tabs(["📊 方式一：過去整年 (365天) 牛熊全週期回測曲線", "⚔️ 方式二：即時模擬盤 PK 資金曲線"])

with tab1:
    if bt_summary and os.path.exists("system_b_backtest_curve.csv"):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("一年後最終淨值 (初始 50U)", f"${bt_summary.get('final', 50)} U", f"{bt_summary.get('return_pct', 0):+.2f}%")
        m2.metric("扣除保本後真實勝率", f"{bt_summary.get('win_rate', 0)}%", f"期望值: {bt_summary.get('expectancy', 0):+.2f}R")
        m3.metric("一年總觸發交易次數", f"{bt_summary.get('trades', 0)} 筆")
        m4.metric("歷史最大回撤 (MDD)", f"{bt_summary.get('max_dd', 0)}%", "安全線 < 15%", delta_color="inverse")

        st.markdown("#### 🔍 牛市 / 熊市 / 震盪市獨立壓力測試表現")
        r1, r2, r3 = st.columns(3)
        bull = bt_summary.get("bull", {})
        bear = bt_summary.get("bear", {})
        rng  = bt_summary.get("range", {})
        r1.metric("🐂 牛市 (Bull)", f"勝率 {bull.get('win_rate', 0)}%", f"期望值 {bull.get('expectancy', 0):+.2f}R ({bull.get('trades', 0)}筆)")
        r2.metric("🐻 熊市 (Bear)", f"勝率 {bear.get('win_rate', 0)}%", f"期望值 {bear.get('expectancy', 0):+.2f}R ({bear.get('trades', 0)}筆)")
        r3.metric("🦀 震盪市 (Range)", f"勝率 {rng.get('win_rate', 0)}%", f"期望值 {rng.get('expectancy', 0):+.2f}R ({rng.get('trades', 0)}筆)")

        bt_df = pd.read_csv("system_b_backtest_curve.csv")
        st.line_chart(bt_df.set_index("timestamp")["System_B_Balance"], height=350)
    else:
        st.write("尚無一年期歷史回測曲線數據，請先執行一次 GitHub Actions。")

with tab2:
    st.markdown("這裡會自動記錄系統 B 每次雲端巡檢的餘額變化，方便與你的系統 A 直接對比！")
    if os.path.exists("system_b_live_curve.csv"):
        live_df = pd.read_csv("system_b_live_curve.csv")
        st.line_chart(live_df.set_index("timestamp")["account_value"], height=300)
        st.dataframe(live_df.tail(10), use_container_width=True)
    else:
        st.write("尚無即時模擬盤曲線紀錄。")
