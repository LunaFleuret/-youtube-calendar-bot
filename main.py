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
    # (generate_token.pyで取得したリフレッシュトークンがここで活躍します)
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
            
        print('--- カレンダーの既存予定と重複チェックをしています... ---')
        now = datetime.datetime.utcnow().isoformat() + 'Z' # 現在時刻をUTCで取得
        events_result = calendar.events().list(
            calendarId=CALENDAR_ID, timeMin=now, maxResults=250, singleEvents=True,
            orderBy='startTime'
        ).execute()
        existing_events = events_result.get('items', [])
        
 
registered_video_ids = set()
for event in existing_events:
    # イベントの拡張プロパティからYouTubeのVideo IDを取得します
    properties = event.get('extendedProperties', {}).get('private', {})
    if 'youtubeVideoId' in properties:
        registered_video_ids.add(properties['youtubeVideoId'])
        
        print(f'カレンダーには現在 {len(registered_video_ids)} 件の将来の配信予定が登録されています。')

        added_count = 0
        for item in response['items']:
            video_id = item['id']['videoId']
            title = item['snippet']['title']
            
            if video_id in registered_video_ids:
                print(f"スキップ: 「{title}」は既に登録済みです。")
                continue

            video_details_request = youtube.videos().list(part="liveStreamingDetails", id=video_id)
            video_details_response = video_details_request.execute()
            
            if not video_details_response['items']: continue
            
            start_time_str = video_details_response['items'][0]['liveStreamingDetails']['scheduledStartTime']
            start_time_dt = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            end_time_dt = start_time_dt + datetime.timedelta(hours=2)

            # main.py の97行目あたり
　　　event_body = {
    'summary': title,
    'description': f'https://www.youtube.com/watch?v={video_id}',
    'start': {'dateTime': start_time_dt.isoformat(), 'timeZone': 'UTC'},
    'end': {'dateTime': end_time_dt.isoformat(), 'timeZone': 'UTC'},
    # 拡張プロパティにYouTubeのVideo IDを保存します
    'extendedProperties': {
        'private': {
            'youtubeVideoId': video_id
        }
    }
}
            
            print(f"新規登録: 「{title}」をカレンダーに追加します...")
            calendar.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
            added_count += 1
            time.sleep(1)

        print(f'--- {added_count}件の新しい予定を追加しました ---')

    except HttpError as error:
        print(f'An error occurred: {error}')

if __name__ == '__main__':
    main()
