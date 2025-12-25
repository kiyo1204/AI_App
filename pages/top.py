import streamlit as st 
from sqlalchemy.sql import text
import time
import hashlib

CONN = st.connection("my_db", type="sql")

# --- データベース作成 ---
try:
    df = CONN.query("SELECT * FROM users", ttl=0)
except Exception as e:
    with CONN.session as s:
            try:
                s.execute(text("DROP TABLE IF EXISTS users;"))
                s.execute(text("""
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user TEXT,
                        password TEXT,
                        email TEXT,
                        window_size INTEGER,
                        stride INTEGER,
                        n_estimators INTEGER,
                        max_depth INTEGER,
                        email_send_timing INTEGER
                    );
                """))
                s.commit()
                st.success("テーブル 'users' を作成しました。")

                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"テーブル作成エラー: {e}")

# --- パスワードのハッシュ化 ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return hashed_text
    return False

# --- ログイン ---
def login_user(user, password):
    with CONN.session as s:
        data = s.execute(
                    text("SELECT * FROM users WHERE user = :user AND password = :password;"), 
                    params=dict(user=user, password=password)
                    ).fetchall()
        return data


# --- 新規登録ダイアログ ---
@st.dialog("新規登録")
def register_dialog():
    with st.form("register_user", clear_on_submit=True):
        user = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        email = st.text_input("メールアドレス", placeholder="123456@abc.de")
        
        submitted = st.form_submit_button("ユーザーを追加")

        if submitted:
            if user and password and email:
                # ユーザー名の重複チェック
                with CONN.session as s:
                    try:
                        existing_user = s.execute(
                            text("SELECT * FROM users WHERE user = :user"),
                            params=dict(user=user)
                        ).fetchone()
                        
                        if existing_user:
                            st.error("このユーザー名は既に使用されています")
                        else:
                            s.execute(
                                text("INSERT INTO users (user, password, email, window_size, stride, n_estimators, max_depth, email_send_timing) VALUES (:user, :password, :email, :window_size, :stride, :n_estimators, :max_depth, :email_send_timing);"),
                                params=dict(user=user, 
                                            password=make_hashes(password), 
                                            email=email,
                                            window_size=60,
                                            stride=30,
                                            n_estimators=400,
                                            max_depth=6,
                                            email_send_timing=0
                                            )
                            )
                            s.commit()
                            st.success("ユーザーを作成しました！")
                            st.session_state["show_register"] = False
                            time.sleep(0.5)
                            st.rerun()
                    except Exception as e:
                        st.error(f"書き込みエラー: {e}")
            else:
                st.warning("名前とパスワードとメールアドレスを入力してください")
    st.session_state["show_register"] = False

# --- ログインダイアログ ---
@st.dialog("ログイン")
def login_dialog():
    user = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("ログイン"):
            st.session_state["show_login"] = False
            st.session_state["show_register"] = False
            hashed_pass = make_hashes(password)
            result = login_user(user, check_hashes(password, hashed_pass))
            if result:
                st.success(f"ようこそ{user}さん")
                st.session_state["login"] = user
                time.sleep(1)
                st.rerun()
            else:
                st.warning("ユーザー名かパスワードが間違っています")
    with col3:
        if st.button("新規登録"):
            st.session_state["show_register"] = True
            st.rerun()
    st.session_state["show_login"] = False


# --- ログアウトダイアログ ---
@st.dialog("ログアウトしますか?", width="small")
def logout_dialog():
    if st.button("ログアウト"):
        st.session_state["login"] = False
        st.session_state["show_login"] = False
        st.rerun()

# --- 設定ダイアログ ---
@st.dialog("設定")
def setting_dialog():
    with CONN.session as s:
        result = s.execute(
            text("SELECT * FROM users WHERE user = :user"),
            params=dict(user=st.session_state["login"])
        ).fetchone()
    
    orig_email = result[3] if result else ""
    orig_window_size = result[4] if result else ""
    orig_stride = result[5] if result else ""
    orig_n_estimators = result[6] if result else ""
    orig_max_depth = result[7] if result else ""
    orig_email_send_timing = result[8] if result else ""

    timing = {
            "歩きスマホ検知後すぐ" : 0,
            "計測終了後, 歩きスマホが検知されていたら" : 1
        } 
    
    with st.form("setting_form", clear_on_submit=True):
        st.header("メールアドレスの設定")
        email = st.text_input(f"現在のメールアドレス: {orig_email}", value=orig_email)
        email_send_timing = st.selectbox("メール送信のタイミング", timing.keys(), index=orig_email_send_timing)
        st.space(size="small")
        
        st.header("スライディングウィンドウパラメータの設定")
        st.subheader("ウィンドウサイズの変更")
        window_size = st.number_input(f"現在のウィンドウサイズ: {orig_window_size}", 10, 1000, orig_window_size, step=10)
        st.subheader("ストライドの変更")
        stride = st.number_input(f"現在のストライド: {orig_stride}", 1, 1000, orig_stride, step=1)
        st.space(size="small")

        st.header("ランダムフォレストパラメータの設定")
        st.subheader("木の数(n_estimators)の変更")
        n_estimators = st.number_input(f"現在の木の数(n_estimators): {orig_n_estimators}", 50, 5000, orig_n_estimators, step=50)
        st.subheader("最大深さ(max_depth)の変更")
        max_depth = st.number_input(f"最大深さ(max_depth): {orig_max_depth}", 1, 10, orig_max_depth, step=1)
        
        submitted = st.form_submit_button("保存", icon=":material/save:")
        if submitted:
            if email:
                with CONN.session as s:
                    try:
                        s.execute(
                            text("UPDATE users SET email = :email, window_size = :window_size, stride = :stride, n_estimators = :n_estimators, max_depth = :max_depth, email_send_timing = :email_send_timing WHERE user = :user"),
                            params=dict(email=email, window_size = window_size, stride = stride, n_estimators = n_estimators, max_depth = max_depth, email_send_timing = timing[email_send_timing], user=st.session_state["login"])
                        )
                        s.commit()
                        st.session_state["window_size"] = window_size
                        st.session_state["stride"] = stride
                        st.session_state["n_estimators"] = n_estimators
                        st.session_state["max_depth"] = max_depth
                        st.session_state["email_send_timing"] = timing[email_send_timing]
                        st.success("設定を更新しました！")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"更新エラー: {e}")
            else:
                st.warning("メールアドレスを入力してください")

# --- アカウント削除ダイアログ ---
@st.dialog("アカウント削除")
def account_delete_dialog():
    with st.form("delete_form", clear_on_submit=True):
        delete_user = st.text_input("ユーザー名を入力")
        delete_password = st.text_input("パスワードを入力", type="password")
        submitted_delete = st.form_submit_button("このユーザーを削除", icon=":material/warning:")

    if submitted_delete:
        if delete_user and delete_password:
            with CONN.session as s:
                if login_user(delete_user, check_hashes(delete_password, make_hashes(delete_password))):
                    try:
                        s.execute(
                            text("DELETE FROM users WHERE user = :user;"),
                            params=dict(user=delete_user)
                        )
                        if delete_user == st.session_state["login"]:
                            st.session_state["login"] = False
                        s.commit()
                        st.success(f"'{delete_user}'を削除")
                        #time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"削除エラー: {e}")
                else:
                    st.error("ユーザー名かパスワードが間違っています")
        else:
            st.warning("ユーザー名とパスワード両方入力してください")

# --- ダイアログの表示判定 ---
if st.session_state["show_register"]:
    register_dialog()
    
if st.session_state["show_login"]:
    login_dialog()



# --- UI設定 ---
if st.session_state["login"] is False: # ログアウト時
    st.title("認知情報科学実験2")
    st.warning("各機能を使う場合はログインしてください")
    if st.sidebar.button("ログイン", icon=":material/logout:"):
        st.session_state["show_login"] = True
        st.rerun()
else: # ログイン時
    user = st.session_state["login"]
    st.title(f"{user}さんようこそ")

    with CONN.session as s:
        result = s.execute(
            text("SELECT * FROM users WHERE user = :user"),
            params=dict(user=st.session_state["login"])
        ).fetchone()

    # セッション状態の初期化(ログイン時)
    states = [
            "window_size", 
            "stride", 
            "n_estimators", 
            "max_depth",
            "email_send_timing"
    ]
    for state, index in zip(states, range(4, 9)):
        st.session_state[state] = result[index]
    
    with st.sidebar:
        st.markdown("**アカウント設定など**")
        if st.button("設定", icon=":material/manage_accounts:"):
            setting_dialog()
        if st.button("アカウント削除", icon=":material/delete_forever:"):
            account_delete_dialog()
        if st.button("ログアウト", icon=":material/logout:"):
            logout_dialog()

    st.title("歩きスマホの危険性について")
    st.write("歩きスマホは、今や日常の風景の一部になっています。しかし、その“ながら行動”は重大な事故につながる危険性をはらんでいます。このページでは、研究データや公共機関の情報をもとに、歩きスマホのリスクを分かりやすく整理しています。")

    st.divider()

    # ------------------------------
    # セクション 1：歩きスマホとは？
    # ------------------------------
    st.header("1. 歩きスマホとは？")
    st.write("""
        歩きスマホとは、**歩行中にスマートフォンを操作・注視する行為**のことです。  
        スマホ普及率の上昇に伴い、年齢層を問わず“無意識に”歩きながら画面を見る人が増えています。
        
        一見すると大したことがなさそうに見えますが、  
        **歩く・見る・考える**という処理を同時に行うことで、注意力が大きく分散してしまいます。
    """)

    st.divider()

    # ------------------------------
    # セクション 2：研究で分かっている危険性
    # ------------------------------
    st.header("2. 研究で明らかになっている危険性")

    with st.expander("2-1 歩行の安定性が低下する（転倒リスクの増加）", expanded=True):
        st.write("""
        京都大学の研究（2024）では、歩きスマホ中の歩行者は  
        **歩行パターンが乱れ、バランスが崩れやすくなる＝転倒リスクが増える** ことが明らかになっています。

        - 歩行速度の低下  
        - 歩幅が細かくなり不安定になる  
        - わずかな段差でもつまずきやすくなる  

        参照：京都大学（Nomura et al., Scientific Reports, 2024）
        """)

    with st.expander("2-2 視線が固定され、周囲の危険に気づけない"):
        st.write("""
        歩きスマホ時は**視線の約80〜90%が画面に固定**されるという研究結果があります。  
        そのため、以下の危険を見落としやすくなります：

        - 車・自転車の接近  
        - 他の歩行者  
        - 障害物（ポール・段差）  
        - 駅のホーム端  

        参照：J-STAGE「歩行中のスマートフォン操作と視線の危険性」
        """)

    with st.expander("2-3 実際の事故データ（東京消防庁）"):
        st.write("""
        東京消防庁によると、「歩きスマホ」が原因で  
        **転倒・衝突事故で救急搬送された例が毎年多数報告**されています。

        - 階段で踏み外して転倒  
        - 電柱・壁・歩行者に衝突  
        - 車道へはみ出して接触  
        - ホームから転落した例もある  

        参照：東京消防庁「歩きスマホ等に係る事故に注意！」
    """)

    st.divider()

    # ------------------------------
    # セクション 3：身近に起こる具体的なリスク
    # ------------------------------
    st.header("3. 歩きスマホが招く具体的リスク")
    st.write("""
    歩きスマホは単なる“マナー違反”ではありません。  
    **ほんの数秒の不注意が重大事故に直結する**可能性があります。

    - ▶ **転倒**（段差・階段・駅のホームでの転落）
    - ▶ **他の歩行者との衝突**
    - ▶ **車・自転車との接触**
    - ▶ **スマホ依存による注意力低下の悪循環**
    - ▶ **肩こり・首への慢性的な負担**

    特に駅構内や交差点周辺では、  
    “自分だけではなく他人の安全も脅かす” 点が重要です。
    """)

    st.divider()
    # ------------------------------
    # セクション 4：今日からできる対策
    # ------------------------------
    st.header("4. 今日からできる安全対策")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🛑 操作は“立ち止まって”する")
        st.write("""
    - 歩きながら通知を確認しない  
    - 返信は立ち止まってから  
    - どうしても使うなら安全な場所で
    """)

    with col2:
        st.subheader("👀 周囲への意識を取り戻す")
        st.write("""
    - ヘッドホン＋スマホ歩行の“二重ながら”を避ける  
    - 夜間や人混みでは特に注意  
    - 駅・道路・交差点ではスマホを持たない
    """)

    st.write("""
    小さな工夫ひとつで、事故リスクを大幅に下げることができます。
    """)

    st.divider()

    # ------------------------------
    # セクション 5：まとめ
    # ------------------------------
    st.header("5. まとめ")
    st.write("""
    歩きスマホは“誰にでも起こりうる”危険をはらんだ行動です。
        
    - ほんの数秒の操作で、重大事故につながる  
    - 視線と意識がスマホに奪われ、周囲の状況を把握できなくなる  
    - 実際に救急搬送例も多数報告されている  

    便利さの裏にあるリスクを知ることで、  
    **自分自身と周囲の安全を守ることができます。**

    「スマホを見る前に、まず足を止める」

    このシンプルな行動が事故を防ぎます。
    """)

    st.divider()

    # ------------------------------
    # 参考文献
    # ------------------------------
    st.header("参考文献・出典")
    st.write("""
    - 京都大学（2024）「歩きスマホによる内因性転倒リスクの増大」  
    - 東京消防庁「歩きスマホ等に係る事故に注意！」  
    - J-STAGE「歩行中のスマートフォン操作と視線の危険性」  
    - モバイル社会研究所（2024）歩きスマホに関する実態調査  
    """)

    st.space(size="small")

st.space(size="medium")
@st.dialog("実験報告書チェックリスト", width="large")
def pdf():
    st.pdf("./app/pages/files/checklist.pdf", height=600)
st.markdown("""
            ### リンク一覧
            * [訓練データリンク](https://chibakoudai-my.sharepoint.com/:x:/r/personal/k24g2040_chibatech_ac_jp/Documents/new_test_data.xlsx?d=w46be6f80755a4cdabc9236be8cee986a&csf=1&web=1&e=6tXcWk)
            * [Google Colaboratory](https://colab.research.google.com/drive/1R84B1Ri8HIS4DRKvQN0En4zuAnRfrgQU?usp=sharing)
            """)
if st.button("実験報告書チェックリスト"):
    pdf()