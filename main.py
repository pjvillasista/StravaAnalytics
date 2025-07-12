import asyncio
import platform
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv
import os
import json
import pandas as pd
from datetime import datetime
import webbrowser
import http.server
import socketserver
import urllib.parse
import time

# Load environment variables
load_dotenv()


# Strava API credentials
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
redirect_url = "http://localhost:8000/callback"


# Set up OAuth2 session
scope = [
    "read_all",
    "profile:read_all",
    "activity:read_all"
    ]
strava = OAuth2Session(client_id=client_id, redirect_url=redirect_url, scope=scope)


# HTTP Server for handling OAuth callback
class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Authorization complete. You can close this window.')
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        query_components = urllib.parse.parse_qs(query)
        auth_code = query_components.get('code', [None])[0]


# Function to get access token
def get_access_token(code):
    token_url = "https://www.strava.com/api/v3/oauth/token"
    token_params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
        'grant_type': 'authorization_code'
    }
    response = strava.post(token_url, data=token_params)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to get token: {response.status_code} - {response.reason}")


# Function to refresh access token
def refresh_access_token(refresh_token):
    token_url = "https://www.strava.com/api/v3/oauth/token"
    token_params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }
    response = strava.post(token_url, data=token_params)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to refresh token: {response.status_code} - {response.reason}")


# Function to get valid access token
def get_valid_access_token():
    token_file = 'strava_token.json'
    if os.path.exists(token_file):
        with open(token_file, 'r') as f:
            token = json.load(f)
        if token['expires_at'] > time.time() + 300:  # 5-minute buffer
            return token['access_token']
        else:
            # Refresh token
            new_token = refresh_access_token(token['refresh_token'])
            with open(token_file, 'w') as f:
                json.dump(new_token, f)
            return new_token['access_token']
    
    # If no valid token, perform OAuth flow
    auth_base_url = "https://www.strava.com/oauth/authorize"
    auth_url, state = strava.authorization_url(auth_base_url, 
        approval_prompt='force',
        response_type='code')
    
    PORT = 8000
    Handler = OAuthHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("Starting local server for OAuth callback...")
        webbrowser.open(auth_url)
        
        global auth_code
        auth_code = None
        
        print("Waiting for authorization...")
        while auth_code is None:
            httpd.handle_request()
        
        token = get_access_token(auth_code)
        with open(token_file, 'w') as f:
            json.dump(token, f)
        return token['access_token']


# Function to fetch activities
def fetch_activities(access_token, per_page=100, max_pages=10):
    activities = []
    page = 1
    
    while page <= max_pages:
        url = f"https://www.strava.com/api/v3/athlete/activities"
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'per_page': per_page, 'page': page}
        
        response = strava.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"Error fetching activities: {response.status_code}")
            break
            
        page_activities = response.json()
        if not page_activities:
            break
            
        activities.extend(page_activities)
        page += 1
        time.sleep(0.1)  # Rate limiting
        
    return activities


# Function to process and save data
def process_activities(activities):
    # Convert to DataFrame
    df = pd.DataFrame([{
        'id': activity['id'],
        'name': activity['name'],
        'distance': activity['distance'] / 1000,  # Convert to km
        'moving_time': activity['moving_time'] / 3600,  # Convert to hours
        'elapsed_time': activity['elapsed_time'] / 3600,  # Convert to hours
        'total_elevation_gain': activity['total_elevation_gain'],
        'type': activity['type'],
        'start_date': activity['start_date'],
        'average_speed': activity['average_speed'] * 3.6,  # Convert to km/h
        'max_speed': activity['max_speed'] * 3.6,  # Convert to km/h
        'calories': activity.get('calories', 0),
        'start_latitude': activity.get('start_latlng', [None, None])[0],
        'start_longitude': activity.get('start_latlng', [None, None])[1]
    } for activity in activities])
    
    # Save to CSV for Tableau
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'strava_activities_{timestamp}.csv'
    df.to_csv(filename, index=False)
    print(f"Data saved to {filename}")
    
    return df

async def main():
    try:
        # Get access token
        access_token = get_valid_access_token()
        
        # Fetch and process activities
        activities = fetch_activities(access_token)
        df = process_activities(activities)
        
        print(f"Retrieved {len(activities)} activities")
        print("\nSample of first activity:")
        print(df.head(1).to_string())
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")

if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())