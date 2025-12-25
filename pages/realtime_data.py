import streamlit as st
import requests as r
import json
import time
import matplotlib.pyplot as plt
import pandas as pd
import pickle
import scipy as sp

from sqlalchemy.sql import text # データベース
import yagmail # メール送信

select_values = {
    "線形加速X軸" : "lin_accX",
    "線形加速Y軸" : "lin_accY",
    "線形加速Z軸" : "lin_accZ",
    "ジャイロX軸" : "gyroX", 
    "ジャイロY軸" : "gyroY", 
    "ジャイロZ軸" : "gyroZ"
    }
get_buffers = select_values.keys()

CONN = st.connection("my_db", type="sql")

# --- メール送信 ---
def send_mail():
    if st.session_state["login"] is not False:
        try:
            # --- メールアドレス取得 ---
            with CONN.session as s:
                email = s.execute(
                    text("SELECT email FROM users WHERE user = :user"),
                    params=dict(user=st.session_state["login"])
                ).fetchone()

            # --- 直近の結果（df）を取得 ---
            df = st.session_state.get("df", None)

            # 該当ラベルのカウント
            if df is not None and "Distracted Walking" in df.columns:
                dw_count = int(df["Distracted Walking"].iloc[0])
            else:
                dw_count = 0

            # stride と sampling_rate（60Hz）から時間計算
            stride = st.session_state.get("stride", 30)
            sampling_rate = 60  # Phyphox想定

            dw_sec = dw_count * (stride / sampling_rate)   # 秒
            dw_min = dw_sec / 60                           # 分

            # --- メール本文 ---
            if st.session_state["email_send_timing"] == 0:
                contents = f"""
<div style="background-color: #fce8e6; border: 1px solid #ea4335; border-left: 5px solid #ea4335; border-radius: 4px; padding: 16px; font-family: sans-serif; max-width: 300px; color: #b31412;">
    <div style="font-weight: bold; font-size: 0.9rem; display: flex; align-items: center; margin-bottom: 8px;">
        <span style="margin-right: 6px; font-size: 1.2rem;">⚠️</span>
        歩きスマホ検知レポート
    </div>
    <div style="font-size: 0.85rem; color: #d93025; line-height: 1.4;">
        <strong>警告:</strong> 歩きスマホを検知しました！<br>
    </div>
</div>
"""
            else:
                contents = f"""
<div style="background-color: #fce8e6; border: 1px solid #ea4335; border-left: 5px solid #ea4335; border-radius: 4px; padding: 16px; font-family: sans-serif; max-width: 300px; color: #b31412;">
    
    <div style="font-weight: bold; font-size: 0.9rem; display: flex; align-items: center; margin-bottom: 8px;">
        <span style="margin-right: 6px; font-size: 1.2rem;">⚠️</span>
        歩きスマホ検知(推定値)
    </div>

    <div style="font-size: 2rem; font-weight: bold; color: #d93025; line-height: 1.2;">
        {dw_min:.2f}
        <span style="font-size: 1rem; font-weight: normal; color: #b31412;">分</span>
    </div>

    <div style="font-size: 0.85rem; color: #d93025; margin-top: 4px;">
        ({dw_sec:.2f} 秒)
    </div>

</div>
"""
            # --- メール送信 ---
            yag = yagmail.SMTP(
                st.secrets["email"]["address"],
                st.secrets["email"]["app_key"]
            )
            yag.send(
                to=email[0],
                subject="RealTime Result",
                contents=contents
            )

        except Exception as e:
            st.error(f"メール送信に失敗しました: {e}")

def extract_features_from_segment(segment):
    features = {}

    #統計量算出
    for col in ['ax', 'ay', 'az', 'wx', 'wy', 'wz']:
        data = segment[col]
        features[f"{col}_mean"]   = data.mean()
        features[f"{col}_std"]    = data.std()
        features[f"{col}_min"]    = data.min()
        features[f"{col}_max"]    = data.max()
        features[f"{col}_median"] = data.median()
        features[f"{col}_range"]  = data.max() - data.min()
        features[f"{col}_q1"] = data.quantile(0.25)
        features[f"{col}_q3"] = data.quantile(0.75)
        features[f'{col}_skew'] = data.skew() #歪度
        features[f'{col}_kurt'] = data.kurt() #尖度
        features[f'{col}_iqr'] = sp.stats.iqr(data) #四分位範囲

    return features

# --- 予測 ---
def pred_data(data, model):
    try:
        features = extract_features_from_segment(data)
        features_df = pd.DataFrame([features])

        pred = model.predict(features_df)[0]

        if pred == 0:
            return "Stop"
        elif pred == 1:
            return "Distracted Walking"
        else:
            return "Not Distracted Walking"
    except Exception as e:
        st.error(f"予測エラー : {e}")
        return "Error"

# --- Phyphoxのデータ取得 ---
def phyphox_get_data(IP):
    url = "http://" + IP + "/get?"
    try:
        response = r.get(url + "&".join(select_values.values()), timeout=0.5).text
        data = json.loads(response)
    except Exception as e:
        # ネットワーク/JSON エラー時は None を返す
        return None

    result = {}
    for buffer in select_values.values():
        try:
            mag_buffer = data["buffer"][buffer]["buffer"][0]
            result[buffer] = mag_buffer
            try:
                pass
            except TypeError:
                st.error(f"{buffer} : データ形式エラー", end="\t")
        except Exception:
            result[buffer] = None
            st.error(f"{buffer} : データがありません", end="\t")
    return result

# リアルタイムプロット. ax を例に時系列で更新表示する
def plot_data(IP, window_size, stride, model, plot_buffer):
    results = {"Distracted Walking" : 0, "Not Distracted Walking" : 0, "Stop" : 0}
    data_buffer = {buffer: [] for buffer in select_values.values()}
    plot_area = st.empty()
    result_area = st.empty()
    stop_button = st.empty()
    
    fig = plt.figure()
    ax = fig.add_subplot()
    
    result = "None"
    email_flag = True
    start_index = 0
    end_index = window_size

    stop_button.button("停止する")

    while True:
        data = phyphox_get_data(IP)

        if data is None:
            time.sleep(0.001)
            continue        
        
        # バッファにデータを追加
        for buffer in select_values.values():
            if data[buffer] is not None:
                data_buffer[buffer].append(data[buffer])
        
        # プロット更新
        ax.clear()
        if len(data_buffer[plot_buffer]) > 0:
            max_data = max(data_buffer[plot_buffer]) + 5
            min_data = min(data_buffer[plot_buffer]) - 5
            ax.plot(range(len(data_buffer[plot_buffer])), data_buffer[plot_buffer])
            ax.set_ylim(min(-5, min_data), max(5, max_data))
            ax.set_xlim(start_index-5, end_index+5)
            ax.set_xlabel("length data")
            ax.set_ylabel(plot_buffer)
        
        # スライディングウィンドウで予測
        if len(data_buffer[plot_buffer]) >= end_index:
            # DataFrameを構築
            if st.session_state["OS"] == "iPhone":
                df_dict = {
                    "ax": data_buffer["lin_accX"][start_index:end_index],
                    "ay": data_buffer["lin_accY"][start_index:end_index],
                    "az": data_buffer["lin_accZ"][start_index:end_index],
                    "wx": data_buffer["gyroX"][start_index:end_index],
                    "wy": data_buffer["gyroY"][start_index:end_index],
                    "wz": data_buffer["gyroZ"][start_index:end_index]
                }
            else:
                df_dict = {
                    "ax": data_buffer["linX"][start_index:end_index],
                    "ay": data_buffer["linY"][start_index:end_index],
                    "az": data_buffer["linZ"][start_index:end_index],
                    "wx": data_buffer["gyrX"][start_index:end_index],
                    "wy": data_buffer["gyrY"][start_index:end_index],
                    "wz": data_buffer["gyrZ"][start_index:end_index]
                }
            df = pd.DataFrame(df_dict)
            
            result = pred_data(df, model)
            results[result] += 1

            if result == "Distracted Walking":
                if st.session_state["email_send_timing"] == 1:
                    st.session_state["email"] = True
                elif email_flag:
                    send_mail()
                    email_flag = False
            
            # ウィンドウをスライド
            start_index += stride
            end_index += stride

        plot_area.pyplot(fig)
        result_area.dataframe(pd.DataFrame([results]), hide_index=True)
        st.session_state["df"] = pd.DataFrame([results])


# --- UI設定 ---
st.set_page_config(page_title="Realtime Processing", page_icon=":material/browse_activity:")
st.title("リアルタイム処理ページ")
if st.session_state["login"]:
    with st.sidebar:
        st.header("スライドパラメータ")
        st.write(f"ウィンドウサイズ: {st.session_state["window_size"]}")
        st.write(f"ストライド: {st.session_state["stride"]}")

        st.header("メール送信")
        if st.session_state["email_send_timing"] == 1:
            st.write("計測終了後, 歩きスマホ検知でメール送信")
        else:
            st.write("歩きスマホ検知後に即時メール送信")

    st.subheader("PhyphoxのリモートアクセスIPを入力")

    if "IP" not in st.session_state:
        st.session_state["IP"] = None
    st.session_state["IP"] = st.text_input("xxx.xxx.xx.xxの形式で入力してください", value=st.session_state["IP"])
    st.subheader("モデルデータをアップロード")
    model_file = st.file_uploader(".pkl形式で読み込み", type=["pkl"])

    if st.session_state["IP"] is not None:
        try:
            os = json.loads(r.get(f"http://{st.session_state['IP']}/meta", timeout=1.0).text)["deviceModel"]
            if "iPhone" not in os:
                st.session_state["OS"] = "Android"
                select_values = {
                                "線形加速X軸" : "linX",
                                "線形加速Y軸" : "linY",
                                "線形加速Z軸" : "linZ",
                                "ジャイロX軸" : "gyrX", 
                                "ジャイロY軸" : "gyrY", 
                                "ジャイロZ軸" : "gyrZ"
                            }
                get_buffers = select_values.keys()
        except: 
            st.warning("端末情報が取得できません")
    plot_buffer = st.sidebar.selectbox("表示する値", get_buffers)

    if st.button("実行する", disabled = not(st.session_state["IP"] and model_file)):
        try:
            url = "http://" + st.session_state["IP"] + "/config"
            response = r.get(url, timeout=1.0).text
            model = pickle.load(model_file)
            st.success("接続完了")
            plot_data(st.session_state["IP"], st.session_state["window_size"], st.session_state["stride"], model, select_values[plot_buffer])
        except Exception as e:
            st.error("接続できませんでした")

    if not (st.session_state["df"]).empty:
        st.subheader("直近の予測結果")
        st.dataframe(st.session_state["df"], hide_index=True)

    if st.session_state["email"]:
        send_mail()
        st.session_state["email"] = False
else:
    st.warning("この機能を使うにはホームでログインしてください", icon="🚨")