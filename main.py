import json
import os
import datetime
import time
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# GitHubの金庫から渡された秘密情報を読み込みます
GCP_CLIENT_SECRET_JSON = os.environ.get('GCP_CLIENT_SECRET')
GCP_TOKEN_JSON = os.environ.get('GCP_TOKEN')

SCOPES = ['https://www.googleapis.com/auth/youtube.readonly', 'https://www.googleapis.com/auth/calendar']

# ★★★★★★★★★★ ここに、対象のYouTubeチャンネルのIDを入力してください ★★★★★★★★★★
YOUTUBE_CHANNEL_ID = 'UCUM6bFim1HuImRHmwkSl8lQ'
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

# ★★★★★★★★★★ ここに、新しいツール専用アカウントで作った「公開用カレンダー」のIDを貼り付けてください ★★★★★★★★★★
CALENDAR_ID = 'a2539a4af3d922263853011ad3e0a7456b6fe092a2491eb6d4fa0e7eef0ae016@group.calendar.google.com'
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

def main():
    """YouTubeの配信予定を取得し、Googleカレンダーに追加するメインの関数"""
    
    # 金庫からの情報がなければ処理を中断
    if not GCP_CLIENT_SECRET_JSON or not GCP_TOKEN_JSON:
        print('エラー: 認証情報が設定されていません。')
        return

    # 文字列の秘密情報から、認証情報オブジェクトを復元します
    client_config = json.loads(GCP_CLIENT_SECRET_JSON)
    token_info = json.loads(GCP_TOKEN_JSON)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    
    # もしトークンが期限切れなら、リフレッシュトークンを使って更新します
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    try:
        youtube = build('youtube', 'v3', credentials=creds)
        calendar = build('calendar', 'v3', credentials=creds)

        print('--- YouTubeの配信予定をチェックしています... ---')
        request = youtube.search().list(
            part='snippet', channelId=YOUTUBE_CHANNEL_ID, eventType='upcoming',
            type='video', maxResults=20
        )
        response = request.execute()

        if not response['items']:
            print('現在、新しい配信予定はありませんでした。')
            return
            
        print('--- 配信予定を1件ずつチェックし、カレンダーと同期します... ---')
        
        added_count = 0
        updated_count = 0
        skipped_count = 0

        for item in response['items']:
            video_id = item['id']['videoId']
            title = item['snippet']['title']
            
            # === ステップ2: イベント検索（新しい方法） ===
            # timeMinを使って未来のイベントを取得し、手動でIDを照合します。
            now = datetime.datetime.utcnow().isoformat() + 'Z'
            try:
                events_result = calendar.events().list(
                    calendarId=CALENDAR_ID,
                    timeMin=now,
                    maxResults=50, # 今後の予定を50件まで取得
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                calendar_events = events_result.get('items', [])
            except HttpError as e:
                print(f"エラー: カレンダーイベントの取得中にエラーが発生しました - {e}")
                continue

            existing_event = None
            for event in calendar_events:
                # イベントの拡張プロパティに保存されたYouTubeのビデオIDを確認します
                private_props = event.get('extendedProperties', {}).get('private', {})
                if private_props.get('youtubeVideoId') == video_id:
                    existing_event = event
                    break # 一致するイベントが見つかったのでループを抜けます

            # 後続のステップで、この existing_event を使って更新または新規追加の判断を行います。

            video_details_request = youtube.videos().list(part="liveStreamingDetails", id=video_id)
            video_details_response = video_details_request.execute()
            
            if not video_details_response['items']: continue
            
            start_time_str = video_details_response['items'][0]['liveStreamingDetails']['scheduledStartTime']
            start_time_dt = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            end_time_dt = start_time_dt + datetime.timedelta(hours=2)

            event_body = {
                'summary': title,
                'description': f'https://www.youtube.com/watch?v={video_id}',
                'start': {'dateTime': start_time_dt.isoformat(), 'timeZone': 'UTC'},
                'end': {'dateTime': end_time_dt.isoformat(), 'timeZone': 'UTC'},
                'extendedProperties': {
                    'private': {
                        'youtubeVideoId': video_id
                    }
                }
            }
            
            # === ステップ3: イベントの更新処理 ===
            if existing_event:
                # 既存のイベントが見つかった場合、タイトルか開始時間が変更されているかチェックします。
                # カレンダーから取得した日時は文字列なので、比較のためにdatetimeオブジェクトに変換します。
                existing_start_time_str = existing_event['start'].get('dateTime')
                existing_start_time_dt = datetime.datetime.fromisoformat(existing_start_time_str.replace('Z', '+00:00'))

                # タイトルまたは開始時刻が変更されているか確認します。
                if existing_event['summary'] != title or existing_start_time_dt != start_time_dt:
                    print(f"更新: 「{title}」の情報をカレンダーで更新します...")
                    calendar.events().update(
                        calendarId=CALENDAR_ID,
                        eventId=existing_event['id'],
                        body=event_body
                    ).execute()
                    updated_count += 1
                else:
                    print(f"スキップ: 「{title}」の情報は既に最新です。")
                    skipped_count += 1

                time.sleep(1) # APIへの負荷を考慮して1秒待機します。
            else:
                # --- ステップ4: イベント新規作成 ---
                # 既存のイベントが見つからなかった場合、新しいイベントとしてカレンダーに追加します。
                print(f"新規登録: 「{title}」をカレンダーに追加します...")
                calendar.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
                added_count += 1
                time.sleep(1) # APIへの負荷を考慮して1秒待機します。

        print('--- 全ての処理が完了しました ---')
        print(f'新規登録: {added_count}件')
        print(f'更新: {updated_count}件')
        print(f'スキップ: {skipped_count}件')

    except HttpError as error:
        print(f'An error occurred: {error}')

if __name__ == '__main__':
    main()
