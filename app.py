import streamlit as st
import pandas as pd
import sqlite3
from PIL import Image
import os
from datetime import datetime
import shutil
from google.cloud import vision
import io
from dotenv import load_dotenv
import re
import MeCab

# 環境変数の読み込み
load_dotenv()

# 変数格納
db_name = os.getenv('DATABASE_NAME')
# GOOGLE_APPLICATION_CREDENTIALSの設定
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_PATH')

# Google Cloud Vision clientの初期化
client = vision.ImageAnnotatorClient()

# データベース接続とテーブル作成
def init_db():
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS receipts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT,
                  merchant TEXT,
                  description TEXT,
                  amount REAL,
                  temp_name TEXT,
                  image_path TEXT)''')
    conn.commit()
    conn.close()

# テキスト抽出関数
def extract_text(image):
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    content = img_byte_arr.getvalue()

    image = vision.Image(content=content)

    response = client.document_text_detection(image=image)
    
    if response.full_text_annotation:
        return response.full_text_annotation.text
    return ""

#レシートの解析関数を改善
def parse_receipt(text):
    lines = text.split('\n')
    date = datetime.now().strftime("%Y-%m-%d")
    merchant = ""
    description = []
    amount = 0

    date_pattern = r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}'

    amount_pattern = "¥[1-9][0-9|,]*"

    amount_candidates = re.findall(amount_pattern, text)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.search(date_pattern, line):
            try:
                date = re.search(date_pattern, line).group()
                date = date.replace('年', '-').replace('月', '-').replace('/', '-')
                date = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                pass
        else:
            description.append(line)

    description = " ".join(description).strip()
    temp_name = f"{date}_{merchant}_{int(amount)}"

    return date , amount_candidates

# データベースにデータを保存
def save_to_database(data, image_path):
    try:
        conn = sqlite3.connect(db_name)
        c = conn.cursor()
        c.execute('INSERT INTO receipts (date, merchant, description, amount, temp_name, image_path) VALUES (?,?,?,?,?,?)', (*data, image_path))
        conn.commit()
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()

# データベースからデータを取得
def get_data_from_db():
    try:
        conn = sqlite3.connect(db_name)
        df = pd.read_sql_query("SELECT * FROM receipts", conn)
        return df
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

# CSVファイルの生成
def create_csv(data):
    return data.to_csv(index=False).encode('utf-8-sig')

# 画像ファイル名の変更
def rename_image(old_path, new_name):
    try:
        directory = os.path.dirname(old_path)
        extension = os.path.splitext(old_path)[1]
        new_path = os.path.join(directory, new_name + extension)
        shutil.move(old_path, new_path)
        return new_path
    except OSError as e:
        print(f"Error renaming file: {e}")
        return old_path

# レシート内容から名詞を抽出
def extract_receipt_nouns(text):
    text = text
    mecab = MeCab.Tagger('-Ochasen -d "C:/Program Files/MeCab/dic/ipadic" -u "C:/Program Files/MeCab/dic/NEologD/NEologd.20200910-u.dic"')

    node = mecab.parseToNode(text)
    output = []

    while node:
        word_type = node.feature.split(",")[1:4]
        print(node.feature, word_type)
        if "固有名詞" in word_type and "組織" in word_type:
            if not node.surface.isdigit():
                output.append(node.surface.upper())
        node = node.next
    
    return output

# Streamlitアプリケーション
def main():
    st.title("レシート管理アプリ")

    init_db()

    menu = ["ホーム", "レシートアップロード", "データ編集", "CSVエクスポート"]
    choice = st.sidebar.selectbox("メニュー", menu)

    if choice == "ホーム":
        st.subheader("ホーム")
        st.write("このアプリでレシートをアップロードし、データを管理できます。")
    # レシートアップロードページ
    elif choice == "レシートアップロード":
        st.subheader("レシートアップロード")
        uploaded_file = st.file_uploader("レシートをアップロードしてください", type=["jpg", "png", "jpeg"])
        
        if uploaded_file is not None:
            image = Image.open(uploaded_file)
            st.image(image, caption='アップロードされた画像', use_column_width=True)
            
            with st.spinner('テキストを抽出中...'):
                # テキスト抽出
                extracted_text = extract_text(image)
                # 名詞抽出用の関数
                result_nouns = extract_receipt_nouns(extracted_text)
            edited_text = st.text_area("抽出されたテキスト（編集可能）", extracted_text, height=250)
            nouns_text = st.text_area("抽出された名詞",result_nouns, height=250)

            parsed_date,amount_candidates = parse_receipt(edited_text)
            with st.form("my_form"):
                st.write("抽出されたデータ:")
                date = st.text_input("日付",parsed_date)
                merchant = st.text_input("取引先名")
                description = st.text_area("摘要")
                x = st.radio("合計金額",amount_candidates)
                amount = re.sub("[¥|,]","",x)
                
                temp_name = f"{date}_{merchant}_{int(amount)}"
                st.write(f"仮名: {temp_name}")
                submitted = st.form_submit_button("保存")
                # submitボタン押下処理
                if submitted:
                    with st.spinner('データを保存中...'):
                        # 一時的に画像を保存
                        temp_image_path = f"temp_{uploaded_file.name}"
                        with open(temp_image_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                        
                        # データベースに保存
                        save_to_database([date, merchant, description, amount, temp_name], temp_image_path)
                        
                        # 画像ファイル名を変更
                        new_image_path = rename_image(temp_image_path, temp_name)
                        
                        st.success('データが正常に保存され、画像ファイル名が更新されました。')
    # データ編集ページ
    elif choice == "データ編集":
        st.subheader("データ編集")
        df = get_data_from_db()
        edited_df = st.data_editor(df)
        
        if st.button('変更を保存'):
            conn = sqlite3.connect('receipts.db')
            edited_df.to_sql('receipts', conn, if_exists='replace', index=False)
            conn.close()
            st.success('変更が保存されました。')           
    # CSVエクスポートページ
    elif choice == "CSVエクスポート":
        st.subheader("CSVエクスポート")
        df = get_data_from_db()
        csv = create_csv(df)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_ai_journal.csv"
        st.download_button(
            label="CSVファイルをダウンロード",
            data=csv,
            file_name=filename,
            mime="text/csv",
        )

if __name__ == '__main__':
    main()