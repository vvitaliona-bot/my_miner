import os
import ssl
import pickle
import time
import requests
import json
import g4f
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from instagrapi import Client

# Полностью отключаем проверку SSL для старых библиотек, если они где-то остались
ssl._create_default_https_context = ssl._create_unverified_context

YOUTUBE_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]

def generate_ai_content(index, context=""):
    """Генерирует виральный заголовок и описание на основе контекста видео."""
    try:
        # Улучшенный промпт с использованием транскрипта
        if context:
            prompt = f"На основе этого текста из видео: '{context}', придумай кликбейтный заголовок (КАПСОМ) и описание для YouTube Shorts/Reels (часть {index}). Добавь 15-20 популярных хештегов. Ответ дай в формате JSON: {{\"title\": \"ЗАГОЛОВОК\", \"description\": \"описание...\"}}. Ответ на русском."
        else:
            prompt = f"Придумай кликбейтный заголовок и описание для YouTube Shorts (часть {index}). Тематика: интересные факты. Заголовок должен быть коротким и капсом. Добавь блок из 15-20 самых популярных хештегов. Ответ дай в формате JSON: {{\"title\": \"ЗАГОЛОВОК\", \"description\": \"описание...\"}}. Ответ на русском."
        
        response = g4f.ChatCompletion.create(
            model=g4f.models.gpt_4,
            messages=[{"role": "user", "content": prompt}],
        )
        
        if response:
            try:
                clean_res = response.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_res)
                desc = data.get("description", "")
                if "#shorts" not in desc.lower():
                    desc += "\n\n#shorts #trending #viral #fyp"
                return data.get("title"), desc
            except:
                return f"ШОК МОМЕНТ #{index}", f"{response}\n\n#shorts #trending #viral"
        
        return f"Auto Reel #{index}", "#shorts #viral #trending #fyp #reels #video #wow"
    except Exception as e:
        print(f"AI Generation error: {e}")
        return f"Auto Reel #{index}", "#shorts #viral #trending #fyp"

def upload_to_youtube(video_path, index, context=""):
    # Генерируем контент через ИИ
    print(f"Generating AI content for reel #{index}...")
    title, description = generate_ai_content(index, context=context)
    print(f"--- AI CONTENT ---\nTITLE: {title}\nDESC: {description[:100]}...\n------------------")
    
    credentials = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            credentials = pickle.load(token)
    
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not os.path.exists('client_secrets.json'):
                print("YouTube client_secrets.json not found.")
                return False
            flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', YOUTUBE_SCOPE)
            credentials = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(credentials, token)

    if credentials.expired:
        credentials.refresh(Request())

    # ПРЯМАЯ ЗАГРУЗКА ЧЕРЕЗ REQUESTS (БЕЗ GOOGLE SDK)
    try:
        url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(os.path.getsize(video_path)),
            "X-Upload-Content-Type": "video/mp4"
        }
        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": "22"
            },
            "status": {"privacyStatus": "public"}
        }

        # Шаг 1: Инициализация загрузки
        response = requests.post(url, headers=headers, data=json.dumps(metadata), verify=False)
        if response.status_code != 200:
            raise Exception(f"Init failed: {response.text}")
        
        upload_url = response.headers.get("Location")
        
        # Шаг 2: Загрузка файла
        with open(video_path, "rb") as f:
            upload_response = requests.put(upload_url, data=f, verify=False)
            
        if upload_response.status_code in [200, 201]:
            video_id = upload_response.json().get("id")
            print(f"SUCCESS: YouTube upload {video_path} - https://youtu.be/{video_id}")
            return True
        else:
            raise Exception(f"Upload failed: {upload_response.text}")

    except Exception as e:
        print(f"ERROR: YouTube direct upload failed: {e}")
        return False

def upload_to_instagram(video_path, caption, username, password):
    try:
        cl = Client()
        # Добавляем случайную задержку, чтобы имитировать человека
        time.sleep(5)
        
        session_file = f"{username}_session.json"
        if os.path.exists(session_file):
            cl.load_settings(session_file)
        
        cl.login(username, password)
        cl.dump_settings(session_file)
        
        media = cl.clip_upload(video_path, caption)
        
        log_msg = f"SUCCESS: Instagram upload {video_path} - Media ID: {media.pk}\n"
        print(log_msg)
        return True
    except Exception as e:
        error_msg = f"ERROR: Instagram upload failed: {e}\n"
        print(error_msg)
        if "blacklist" in str(e):
            print("СОВЕТ: Instagram заблокировал ваш IP. ВКЛЮЧИТЕ VPN на компьютере!")
        return False

def upload_to_vk(video_path, title, description, access_token, group_id):
    """Загружает видео в VK Клипы от имени группы, используя токен пользователя."""
    try:
        # 1. Получаем URL для загрузки
        save_url = "https://api.vk.com/method/video.save"
        params = {
            "name": title,
            "description": description,
            "wallpost": 1,
            "group_id": group_id, # Загружаем в группу
            "v": "5.131",
            "access_token": access_token # Здесь должен быть ТОКЕН ПОЛЬЗОВАТЕЛЯ
        }
        
        res = requests.get(save_url, params=params).json()
        if "error" in res:
            error_msg = res['error']['error_msg']
            if "Group authorization failed" in error_msg:
                print("ОШИБКА VK: Вы использовали токен группы. Нужен ТОКЕН ПОЛЬЗОВАТЕЛЯ (админа).")
            raise Exception(f"VK video.save error: {error_msg}")
            
        upload_url = res["response"]["upload_url"]
        video_id = res["response"]["video_id"]
        owner_id = res["response"]["owner_id"]
        
        # 2. Загружаем файл
        with open(video_path, "rb") as f:
            files = {"video_file": f}
            upload_res = requests.post(upload_url, files=files).json()
            
        if "error" in upload_res:
            raise Exception(f"VK upload error: {upload_res['error']}")
            
        print(f"SUCCESS: VK upload {video_path} - Video ID: {video_id} (Owner: {owner_id})")
        return True
        
    except Exception as e:
        print(f"ERROR: VK upload failed: {e}")
        return False
