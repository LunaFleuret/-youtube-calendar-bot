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

def get_existing_events(calendar_service, calendar_id):
    """カレンダーの既存イベントを取得し、重複チェック用のデータを準備する"""
    print('--- カレンダーの既存予定と重複チェックをしています... ---')
    
    # 過去30日から将来3年までのイベントを取得（長期予定の重複を防ぐため）
    now = datetime.datetime.utcnow()
    time_min = (now - datetime.timedelta(days=30)).isoformat() + 'Z'
    time_max = (now + datetime.timedelta(days=1095)).isoformat() + 'Z'  # 3年 = 1095日
    
    events_result = calendar_service.events().list(
        calendarId=calendar_id, 
        timeMin=time_min, 
        timeMax=time_max,
        maxResults=1000, 
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    
    existing_events = events_result.get('items', [])
    
    # 重複チェック用のデータ構造
    registered_video_ids = set()
    registered_titles = set()
    registered_start_times = set()
    
    for event in existing_events:
        # YouTubeのURLからvideo_idを抽出
        description = event.get('description', '')
        if 'youtube.com/watch?v=' in description:
            video_id = description.split('v=')[-1].split('&')[0]  # パラメータを除去
            registered_video_ids.add(video_id)
        
        # タイトルを正規化して保存
        title = event.get('summary', '').strip()
        if title:
            # タイトルを正規化（空白を除去、小文字化）
            normalized_title = ' '.join(title.lower().split())
            registered_titles.add(normalized_title)
        
        # 開始時刻を保存（重複チェック用）
        start_time = event.get('start', {}).get('dateTime')
        if start_time:
            # 時刻を分単位で丸める（秒以下の違いを無視）
            start_dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            rounded_start = start_dt.replace(second=0, microsecond=0)
            registered_start_times.add(rounded_start)
    
    print(f'カレンダーには現在 {len(existing_events)} 件のイベントが登録されています。')
    print(f'重複チェック対象: Video ID {len(registered_video_ids)}件, タイトル {len(registered_titles)}件, 開始時刻 {len(registered_start_times)}件')
    
    # デバッグ用：取得したイベントの詳細を表示
    if existing_events:
        print('--- 取得した既存イベントの詳細 ---')
        for event in existing_events[:5]:  # 最初の5件のみ表示
            title = event.get('summary', 'No title')
            start_time = event.get('start', {}).get('dateTime', 'No time')
            description = event.get('description', '')
            video_id = ''
            if 'youtube.com/watch?v=' in description:
                video_id = description.split('v=')[-1].split('&')[0]
            print(f'  タイトル: {title}')
            print(f'  開始時刻: {start_time}')
            print(f'  Video ID: {video_id}')
            print('  ---')
    
    return registered_video_ids, registered_titles, registered_start_times

def is_duplicate_event(video_id, title, start_time, registered_video_ids, registered_titles, registered_start_times):
    """イベントが重複しているかチェックする"""
    
    # 1. Video IDによる重複チェック
    if video_id in registered_video_ids:
        return True, "Video ID重複"
    
    # 2. タイトルによる重複チェック
    normalized_title = ' '.join(title.lower().split())
    if normalized_title in registered_titles:
        return True, "タイトル重複"
    
    # 3. 開始時刻による重複チェック（5分以内の差を重複とみなす）
    if start_time:
        rounded_start = start_time.replace(second=0, microsecond=0)
        for existing_start in registered_start_times:
            time_diff = abs((rounded_start - existing_start).total_seconds())
            if time_diff <= 300:  # 5分 = 300秒
                return True, "開始時刻重複"
    
    return False, ""

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
        
        # 既存イベントを取得して重複チェック用データを準備
        registered_video_ids, registered_titles, registered_start_times = get_existing_events(calendar, CALENDAR_ID)
            
        print('--- 配信予定を1件ずつチェックし、カレンダーと同期します... ---')
        
        added_count = 0
        updated_count = 0
        skipped_count = 0

        for item in response['items']:
            video_id = item['id']['videoId']
            title = item['snippet']['title']
            
            # === ステップ2: イベント検索 ===
            # video_id を使って、カレンダーに既に同じ予定が存在しないか検索します。
            # privateExtendedProperty を使うことで、特定のカスタムデータを持つイベントだけを絞り込めます。
            existing_event = None
            try:
                events_result = calendar.events().list(
                    calendarId=CALENDAR_ID,
                    privateExtendedProperty=f"youtubeVideoId='{video_id}'",
                    maxResults=1
                ).execute()
                if events_result.get('items'):
                    existing_event = events_result.get('items')[0]
            except HttpError as e:
                print(f"エラー: カレンダーの検索中にエラーが発生しました - {e}")
                continue # エラーが発生した場合は、このビデオの処理をスキップします

            video_details_request = youtube.videos().list(part="liveStreamingDetails", id=video_id)
            video_details_response = video_details_request.execute()
            
            if not video_details_response['items']: 
                print(f"スキップ: 「{title}」の配信詳細が取得できませんでした。")
                continue
            
            start_time_str = video_details_response['items'][0]['liveStreamingDetails']['scheduledStartTime']
            start_time_dt = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            end_time_dt = start_time_dt + datetime.timedelta(hours=2)
            
            # 重複チェック（既存イベントが見つからない場合のみ）
            if not existing_event:
                print(f"重複チェック実行: 「{title}」 (Video ID: {video_id})")
                is_duplicate, reason = is_duplicate_event(
                    video_id, title, start_time_dt, registered_video_ids, registered_titles, registered_start_times
                )
                
                if is_duplicate:
                    print(f"スキップ: 「{title}」は既に登録済みです。理由: {reason}")
                    skipped_count += 1
                    continue
                else:
                    print(f"重複なし: 「{title}」は新規イベントとして追加されます")

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
                
                # 新しく追加したイベントの情報を重複チェック用データに追加
                registered_video_ids.add(video_id)
                normalized_title = ' '.join(title.lower().split())
                registered_titles.add(normalized_title)
                registered_start_times.add(start_time_dt.replace(second=0, microsecond=0))
                
                time.sleep(1) # APIへの負荷を考慮して1秒待機します。

        print('--- 全ての処理が完了しました ---')
        print(f'新規登録: {added_count}件')
        print(f'更新: {updated_count}件')
        print(f'スキップ: {skipped_count}件')

    except HttpError as error:
        print(f'An error occurred: {error}')

if __name__ == '__main__':
    main()
