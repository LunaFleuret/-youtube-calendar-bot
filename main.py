import datetime
# 日本時間を扱うためのライブラリ
import pytz

def run():
    # タイムゾーンを東京に設定
    jst = pytz.timezone('Asia/Tokyo')
    # 現在の日本時間を取得
    now = datetime.datetime.now(jst)
    # 現在時刻を表示する
    print(f"プログラムが実行されました。現在時刻: {now.strftime('%Y-%m-%d %H:%M:%S')}")

# このファイルが直接実行されたときに、run()関数を呼び出す
if __name__ == '__main__':
    run()