import streamlit as st
import pandas as pd

st.set_page_config(page_title="ホーム", page_icon=":shark:")

pages = {
    "ページ一覧" : [
        st.Page(page="pages/top.py", title="ホーム", icon=":material/home:"),
        st.Page(page="pages/train_model.py", title="モデル作成ページ", icon=":material/network_intelligence_update:"),
        st.Page(page="pages/realtime_data.py", title="リアルタイムデータの処理", icon=":material/browse_activity:")
    ]
}

# --- セッション状態の初期化 ---
states = ["show_login",
            "login",
            "show_register", 
            "df", 
            "email",
            "OS",
        ]

for state in states:
    if state not in st.session_state and state == "OS":
        st.session_state[state] = "iPhone"
    elif state == "df" and state not in st.session_state:
        st.session_state[state] = pd.DataFrame({
            "結果" : [None],
        })
    elif state not in st.session_state:
        st.session_state[state] = False

pg = st.navigation(pages)
pg.run()