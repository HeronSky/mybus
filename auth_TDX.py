import requests
import json
from datetime import datetime, timedelta
import os

app_id = os.environ.get('TDX_APP_ID', 'YOUR_TDX_APP_ID')
app_key = os.environ.get('TDX_APP_KEY', 'YOUR_TDX_APP_KEY')

auth_url="https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"

_access_token_cache = {
    "token": None,
    "expires_at": datetime.now()
}

class Auth():
    def __init__(self, app_id, app_key):
        self.app_id = app_id
        self.app_key = app_key

    def get_auth_header(self):
        content_type = 'application/x-www-form-urlencoded'
        grant_type = 'client_credentials'
        return{
            'content-type' : content_type,
            'grant_type' : grant_type,
            'client_id' : self.app_id,
            'client_secret' : self.app_key
        }

def get_tdx_access_token():
    global _access_token_cache
    now = datetime.now()
    if not _access_token_cache["token"] or _access_token_cache["expires_at"] <= (now + timedelta(minutes=10)):
        auth_instance = Auth(app_id, app_key)
        try:
            auth_response = requests.post(auth_url, auth_instance.get_auth_header())
            auth_response.raise_for_status()
            auth_data = auth_response.json()
            token = auth_data.get('access_token')
            expires_in = auth_data.get('expires_in', 86400) 
            _access_token_cache["token"] = token
            _access_token_cache["expires_at"] = now + timedelta(seconds=expires_in - 900) 
            return token
        except requests.exceptions.RequestException:
            return None
        except json.JSONDecodeError:
            return None
    return _access_token_cache["token"]

def fetch_tdx_data_with_token(api_url, access_token, params=None):
    if not access_token:
        return (None, "NO_TOKEN")
    
    headers = {
        'authorization': 'Bearer ' + access_token,
        'Accept-Encoding': 'gzip'
    }
    response = None
    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        return (response.json(), None)
    except requests.exceptions.HTTPError as http_err:
        status_code = http_err.response.status_code if http_err.response else "UNKNOWN_HTTP_STATUS"
        return (None, status_code)
    except requests.exceptions.RequestException:
        return (None, "REQUEST_EXCEPTION")
    except json.JSONDecodeError:
        return (None, "JSON_DECODE_ERROR")