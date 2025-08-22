from google_auth_oauthlib.flow import InstalledAppFlow

# YouTubeの読み取りと、カレンダーの読み書き、両方の権限を要求します。
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly', 'https://www.googleapis.com/auth/calendar']

def main():
    """
    ユーザーに認証を求め、リフレッシュトークンを含むtoken.jsonを生成する。
    """
    print("ブラウザを起動して認証を行ってください...")
    # client_secret.jsonから認証フローを作成し、実行します。
    # これにより、ユーザーはブラウザで認証を行い、プログラムは資格情報を得ます。
    flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
    creds = flow.run_local_server(port=0)

    # 資格情報を'token.json'ファイルに保存します。
    # この中には、私たちが求めるリフレッシュトークンが含まれています。
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    
    print("\n認証に成功し、'token.json' ファイルを作成しました。")
    print("このファイルは、GitHubに秘密情報として設定するために必要です。")

if __name__ == '__main__':
    main()