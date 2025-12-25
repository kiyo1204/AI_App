import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st
import pickle
import scipy as sp
import os, tempfile
import numpy as np
import matplotlib.animation as animation
from matplotlib.animation import PillowWriter

from sklearn import metrics
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay

# ====== 定数 ======
LABEL_NAMES = {0: "Stop", 1: "Distracted\nWalking", 2: "Not Distracted\nWalking"}
FEATURE_COLS = ["ax", "ay", "az", "wx", "wy", "wz"]
SAMPLING_RATE = 100

# ====== 特徴量抽出 ======
def extract_features_from_segment(segment: pd.DataFrame) -> dict:
    for c in FEATURE_COLS:
        if c not in segment.columns:
            raise ValueError(f"列が不足しています: {c}")

    feats = {}
    for col in FEATURE_COLS:
        s = segment[col]
        feats[f"{col}_mean"]   = s.mean() # 平均値
        feats[f"{col}_std"]    = s.std() # 偏差
        feats[f"{col}_min"]    = s.min() # 最小値
        feats[f"{col}_max"]    = s.max() # 最大値
        feats[f"{col}_median"] = s.median() # 中央値
        feats[f"{col}_range"]  = s.max() - s.min() # 範囲
        feats[f"{col}_q1"] = s.quantile(0.25) # 第一四分位数
        feats[f"{col}_q3"] = s.quantile(0.75) # 第三四分位数
        feats[f'{col}_skew'] = s.skew() # 歪度
        feats[f'{col}_kurt'] = s.kurt() # 尖度
        feats[f'{col}_iqr'] = sp.stats.iqr(s) # 四分位範囲

    if "class" in segment.columns and not segment["class"].empty:
        feats["class"] = segment["class"].mode().iloc[0]

    return feats


def segment_and_extract(df: pd.DataFrame, window_size: int, stride: int) -> pd.DataFrame:
    rows, n = [], len(df)
    for start in range(0, max(n - window_size + 1, 0), stride):
        seg = df.iloc[start : start + window_size]
        rows.append(extract_features_from_segment(seg))

    if not rows:
        raise ValueError("ウィンドウが作れません。window/stride を見直してください。")

    return pd.DataFrame(rows)


# ====== 学習・評価 ======
def train_and_evaluate(feature_df: pd.DataFrame, tree: int, max_depth: int):
    if "class" not in feature_df.columns:
        raise ValueError("特徴量データに 'class' 列がありません。")

    X = feature_df.drop(columns=["class"])
    y = feature_df["class"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.8, stratify=y, random_state=42)

    rf = RandomForestClassifier(n_estimators=tree, max_depth=max_depth, random_state=42)
    rf.fit(Xtr, ytr)

    yhat = rf.predict(Xte)
    acc = metrics.accuracy_score(yte, yhat)

    classes_sorted = sorted(pd.unique(y))
    disp_labels = [LABEL_NAMES.get(c, str(c)) for c in classes_sorted]
    cm = confusion_matrix(yte, yhat, labels=classes_sorted)

    fig, ax = plt.subplots(figsize=(6, 5), dpi=150)
    ConfusionMatrixDisplay(cm, display_labels=disp_labels).plot(ax=ax, colorbar=False)
    ax.set_title("Confusion Matrix - RandomForest")
    fig.tight_layout()

    return rf, acc, fig

def predict_segment(model, df_segment: pd.DataFrame):
    feats = extract_features_from_segment(df_segment)
    X = pd.DataFrame([feats]).drop(columns=[c for c in ["class"] if c in feats], errors="ignore")
    pred = model.predict(X)[0]
    return LABEL_NAMES.get(pred, str(pred))

def make_prediction_gif(pred_df: pd.DataFrame, model, window_size: int, stride: int) -> bytes:
    # 必須列
    need = {"time", "ax"}
    if not need.issubset(set(pred_df.columns)):
        raise ValueError(f"予測データに必要な列が足りません: {sorted(list(need - set(pred_df.columns)))}")

    t = pred_df["time"].to_numpy()
    y = pred_df["ax"].to_numpy()
    total = len(y)

    fig, ax = plt.subplots(figsize=(10, 5), dpi=130)
    ax.plot(t, y, alpha=0.5, label="Full ax")
    (dyn_line,) = ax.plot([], [], lw=2, label="Window")
    ax.legend(loc="upper right")
    ax.set_xlabel("Time")
    ax.set_ylabel("ax")
    ax.set_ylim(np.min(y) - 0.5, np.max(y) + 0.5)
    title = ax.set_title("result: (computing...)")

    def update(i):
        start = i * stride
        end = min(start + window_size, total)
        if end - start < window_size:
            start = max(0, total - window_size)
            end = total
        dyn_line.set_data(t[start:end], y[start:end])

        seg = pred_df.iloc[start:end].drop(columns=[c for c in ["time","detail"] if c in pred_df.columns], errors="ignore")
        title.set_text(f"result: {predict_segment(model, seg)}")
        return dyn_line, title

    frames = max((total - window_size) // stride + 1, 1)
    ani = animation.FuncAnimation(fig, update, frames=frames, interval=400)
    plt.close(fig)

    # 一時ファイルに保存してから bytes 読み出し
    with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as tmp:
        tmp_path = tmp.name
    ani.save(tmp_path, writer=PillowWriter(fps=5))
    with open(tmp_path, "rb") as f:
        data = f.read()
    os.remove(tmp_path)
    return data

# ====== 予測ウィンドウごとのラベルと時間（集計用） ======
def predict_windows_with_time(pred_df: pd.DataFrame, model, window_size: int, stride: int) -> pd.DataFrame:
    """
    pred_data.xlsx を window/stride でスライドし、
    各ウィンドウの予測ラベルと [開始時刻, 終了時刻, 継続時間] を返す。
    time列が数値(秒等)ならそのまま、日時なら先頭を0秒として差分秒に換算。
    """
    if "time" not in pred_df.columns:
        raise ValueError("予測データに 'time' 列が必要です。")

    time_col = pred_df["time"]

    # time列が数値ならそのまま、日時なら秒へ
    if np.issubdtype(time_col.dtype, np.number):
        tsec = time_col.to_numpy().astype(float)
    else:
        t_dt = pd.to_datetime(time_col, errors="coerce")
        if t_dt.isna().any():
            # 変換不可が含まれる場合はインデックスを秒扱い（1サンプル=1）
            tsec = np.arange(len(time_col), dtype=float)
        else:
            t0 = t_dt.iloc[0]
            tsec = (t_dt - t0).dt.total_seconds().to_numpy()

    n = len(pred_df)
    rows = []
    idx = 0
    while True:
        start = idx * stride
        if start >= n:
            break
        end = min(start + window_size, n)
        if end - start < window_size:
            start = max(0, n - window_size)
            end = n

        seg = pred_df.iloc[start:end].drop(columns=[c for c in ["time","detail"] if c in pred_df.columns], errors="ignore")
        label = predict_segment(model, seg)

        t_start = float(tsec[start])
        t_end   = float(tsec[end - 1])
        dur     = max(0.0, t_end - t_start)

        rows.append({
            "start_time_s": t_start,
            "end_time_s":   t_end,
            "duration_s":   dur,
            "label":        label
        })

        idx += 1
        if end >= n:
            break

    return pd.DataFrame(rows)

# ====== Streamlit UI ======
st.set_page_config(page_title="train model", page_icon=":material/network_intelligence_update:")
st.title("モデル作成ページ")
if st.session_state["login"]:
    with st.sidebar:
        st.header("スライドパラメータ")
        st.write(f'ウィンドウサイズ : {st.session_state["window_size"]}')
        st.write(f'ストライド : {st.session_state["stride"]}')

        st.header("ランダムフォレストパラメータ")
        st.write(f'木の数(n_estimators) : {st.session_state["n_estimators"]}')
        st.write(f'最大深さ(max_depth) : {st.session_state["max_depth"]}')

    st.subheader("学習用Excel（train_data.xlsx）をアップロード")
    model_file = st.file_uploader("列: time, ax, ay, az, wx, wy, wz, class, detail（detailは任意）", type=["xlsx"])
    st.subheader("テスト用Excel(test_data.xlsx) をアップロード")
    pred_file = st.file_uploader("列: time, ax, ay, az, wx, wy, wz", type=["xlsx"])

    # -------- 実行ボタン --------
    if st.button("実行する", disabled=not(model_file)):
        try:
            with st.spinner("モデル作成中..."):
                train_df = pd.read_excel(model_file)
                train_df = train_df.drop(columns=[c for c in ["time", "detail"] if c in train_df.columns], errors="ignore")
                    
                feat_df = segment_and_extract(train_df, st.session_state["window_size"], st.session_state["stride"])
                st.success(f"特徴量: {feat_df.shape[0]} ウィンドウ / {feat_df.shape[1]} 列")

                rf, acc, fig_cm = train_and_evaluate(feat_df, st.session_state["n_estimators"], st.session_state["max_depth"])
                st.metric("RandomForest accuracy", f"{acc:.4f}")
                st.pyplot(fig_cm, clear_figure=True)
                    
                # 予測データ & GIF
                pred_df = pd.read_excel(pred_file)
                gif_bytes = make_prediction_gif(pred_df, rf, st.session_state["window_size"], st.session_state["stride"])
                st.image(gif_bytes, caption="prediction_animation.gif", use_container_width=True)
                st.download_button("GIFをダウンロード", data=gif_bytes, file_name="prediction_animation.gif", mime="image/gif")

                # === 予測ラベル × 時間の集計 ===
                win_df = predict_windows_with_time(pred_df, rf, st.session_state["window_size"], st.session_state["stride"])
                if not win_df.empty:
                    # ラベルごと合計秒
                    agg = (win_df
                        .groupby("label", as_index=False)["duration_s"].sum()
                        .sort_values("duration_s", ascending=False))
                    total_sec = agg["duration_s"].sum()
                    agg["ratio_%"] = (agg["duration_s"] / total_sec * 100.0) if total_sec > 0 else 0.0

                    st.subheader("予測ラベルごとの合計時間")
                    st.dataframe(agg, use_container_width=True, hide_index=True)

                    # メトリクス（Stop / Distracted / Not Distracted）
                    def fmt_hms(sec: float) -> str:
                        m, s = divmod(int(round(sec)), 60)
                        return f"{m:02d}:{s:02d}"

                    c1, c2, c3 = st.columns(3)
                    def show_metric(col, label_name, display_name):
                        v = agg.loc[agg["label"] == label_name, "duration_s"]
                        sec = float(v.iloc[0]) if not v.empty else 0.0
                        col.metric(display_name, f"{sec:.2f} s")
                        col.caption(f"⏱ {fmt_hms(sec)}")

                    show_metric(c1, "Stop", "Stop")
                    show_metric(c2, "Distracted\nWalking", "Distracted Walking")
                    show_metric(c3, "Not Distracted\nWalking", "Not Distracted Walking")

                    # CSV ダウンロード（集計）
                    st.download_button(
                        "ラベル別合計時間をCSVで保存",
                        data=agg.to_csv(index=False).encode("utf-8-sig"),
                        file_name="label_duration_summary.csv",
                        mime="text/csv",
                    )
                    # CSV ダウンロード（ウィンドウ詳細）
                    st.download_button(
                        "ウィンドウごとの予測と時間（詳細CSV）",
                        data=win_df.to_csv(index=False).encode("utf-8-sig"),
                        file_name="window_predictions.csv",
                        mime="text/csv",
                    )
                    # ====== 学習モデル 保存（正常動作するよう修正済み）======
                    st.download_button(
                        "学習モデルをpickle形式で保存",
                        data=pickle.dumps(rf),
                        file_name="model.pkl",
                    )
                else:
                    st.info("ウィンドウが作れませんでした。window/stride を見直してください。")
        except Exception as e:
            st.error(f"エラー: {e}")
else:
    st.warning("この機能を使うにはホームでログインしてください", icon="🚨")
