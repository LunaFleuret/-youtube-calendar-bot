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
YOUTUBE_CHANNEL_ID = 'UCUM6bFim1HuImRHmwkSl8lQ' # ここはあなたのIDに書き換えてください
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

# ★★★★★★★★★★ ここに、新しいツール専用アカウントで作った「公開用カレンダー」のIDを貼り付けてください ★★★★★★★★★★
CALENDAR_ID = 'a2539a4af3d922263853011ad3e0a7456b6fe092a2491eb6d4fa0e7eef0ae016@group.calendar.google.com' # ここはあなたのIDに書き換えてください
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

def get_video_id_from_description(description):
    """イベントの説明文からYouTubeのビデオIDを抽出する関数"""
    if description and 'youtube.com/watch?v=' in description:
        return description.split('v=')[-1]
    return None

def main():
    """YouTubeの配信予定をGoogleカレンダーと同期する（新規・更新・削除に対応）"""
    
    if not GCP_CLIENT_SECRET_JSON or not GCP_TOKEN_JSON:
        print('エラー: 認証情報が設定されていません。')
        return

    client_config = json.loads(GCP_CLIENT_SECRET_JSON)
    token_info = json.loads(GCP_TOKEN_JSON)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    try:
        youtube = build('youtube', 'v3', credentials=creds)
        calendar = build('calendar', 'v3', credentials=creds)

        # --- 1. YouTubeから未来の配信予定を取得 ---
        print('--- 1. YouTubeの配信予定を取得しています... ---')
        youtube_events = {}
        request = youtube.search().list(
            part='id,snippet', channelId=YOUTUBE_CHANNEL_ID, eventType='upcoming',
            type='video', maxResults=50
        )
        response = request.execute()
        
        video_ids_to_fetch = [item['id']['videoId'] for item in response.get('items', [])]
        if video_ids_to_fetch:
            video_details_request = youtube.videos().list(part="liveStreamingDetails,snippet", id=",".join(video_ids_to_fetch))
            video_details_response = video_details_request.execute()
            for item in video_details_response.get('items', []):
                video_id = item['id']
                start_time_str = item.get('liveStreamingDetails', {}).get('scheduledStartTime')
                title = item.get('snippet', {}).get('title', '（タイトル不明）')
                if start_time_str:
                    youtube_events[video_id] = {'title': title, 'start_time': start_time_str}
        
        print(f"YouTube上で {len(youtube_events)} 件の配信予定を見つけました。")

        # --- 2. Googleカレンダーから未来の予定を取得 ---
        print('--- 2. Googleカレンダーの既存予定を取得しています... ---')
        calendar_events = {}
        now_utc_dt = datetime.datetime.now(datetime.timezone.utc)
        now_utc_iso = now_utc_dt.isoformat()
        
        events_result = calendar.events().list(
            calendarId=CALENDAR_ID, timeMin=now_utc_iso, maxResults=250, singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        for event in events_result.get('items', []):
            video_id = get_video_id_from_description(event.get('description'))
            if video_id:
                calendar_events[video_id] = {
                    'event_id': event['id'], 
                    'start_time': event['start'].get('dateTime'),
                    'title': event.get('summary')
                }

        print(f"カレンダー上で {len(calendar_events)} 件の配信予定を見つけました。")

        # --- 3. 比較して、新規追加・更新・削除を実行 ---
        print('--- 3. 予定を比較し、同期を開始します... ---')
        youtube_video_ids = set(youtube_events.keys())
        calendar_video_ids = set(calendar_events.keys())

        # パターン①：新規追加 (YouTubeにはあるが、カレンダーにはない)
        for video_id in youtube_video_ids - calendar_video_ids:
            event_data = youtube_events[video_id]
            title = event_data['title']
            start_time_dt = datetime.datetime.fromisoformat(event_data['start_time'].replace('Z', '+00:00'))
            
            # 【安全装置】配信開始時刻が、現在時刻より未来の場合のみ追加する
            if start_time_dt < now_utc_dt:
                print(f"【スキップ】: 「{title}」は既に開始または終了しているため、追加しません。")
                continue

            end_time_dt = start_time_dt + datetime.timedelta(hours=2)

            event_body = {
                'summary': title, 'description': f'https://www.youtube.com/watch?v={video_id}',
                'start': {'dateTime': start_time_dt.isoformat(), 'timeZone': 'UTC'},
                'end': {'dateTime': end_time_dt.isoformat(), 'timeZone': 'UTC'},
            }
            print(f"【新規】: 「{title}」を追加します。")
            calendar.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
            time.sleep(1)

        # パターン②：更新 (両方にあるが、時間が違う場合のみ)
        for video_id in youtube_video_ids.intersection(calendar_video_ids):
            youtube_event = youtube_events[video_id]
            calendar_event = calendar_events[video_id]
            
            youtube_start_time_utc = youtube_event['start_time']
            calendar_start_time_utc = calendar_event['start_time'].replace('+00:00', 'Z')
            
            # 時間が変更されているかだけをチェック