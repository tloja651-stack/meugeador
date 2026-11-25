from google_auth_oauthlib.flow import InstalledAppFlow
flow=InstalledAppFlow.from_client_secrets_file('credentials.json',['https://www.googleapis.com/auth/gmail.readonly'])
creds=flow.run_local_server(port=0,prompt='consent',access_type='offline')
print('GMAIL_REFRESH_TOKEN='+str(creds.refresh_token))
print('GOOGLE_CLIENT_ID='+creds.client_id)
print('GOOGLE_CLIENT_SECRET='+creds.client_secret)
