from flask import Flask, render_template, request, send_from_directory, jsonify
import os
import yt_dlp
import random
import uuid
import time
import threading
import sqlite3
from faster_whisper import WhisperModel
import torch
from concurrent.futures import ThreadPoolExecutor
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, AudioFileClip
from uploader import upload_to_youtube, upload_to_instagram, upload_to_vk

app = Flask(__name__)
DB_PATH = 'tasks.db'
UPLOAD_FOLDER = 'static/videos'
OUTPUT_FOLDER = 'static/reels'
MUSIC_FOLDER = 'static/music'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(MUSIC_FOLDER, exist_ok=True)

# Конфигурация
INSTA_USERNAME = 'stasb_as'
INSTA_PASSWORD = 'fafa007'
VK_GROUP_ID = '237843410'
VK_TOKEN = 'vk1.a.GnHYV33karBYeFZzQ4eo0E7P43Y1Rs3Plg8JldxYvjL81Wi51RWWcycWpZDYu4gWgo_vlPoIUfZNR8eGXtFsHZlnfDGTZez86c1oMrJJ1GONCGkshX3O3UXWBIffEoh1sg85grvfmEvkb8eoeMJqOcsOBkFcR6qv0Nurlg1wxrjozY6Rh0yk-fmeH78qvIVwTru-DAf1b8vPC-TTj4riyg'

# Инициализация БД
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS tasks 
            (id TEXT PRIMARY KEY, url TEXT, status TEXT, platforms TEXT, created_at TIMESTAMP)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS task_reels 
            (task_id TEXT, filename TEXT)''')
init_db()

# Инициализация Faster-Whisper
print("Loading Faster-Whisper model (tiny)...")
device = "cpu" 
whisper_model = WhisperModel("tiny", device=device, compute_type="float32")

def cleanup_old_files():
    """Очистка временных файлов при запуске"""
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                try:
                    file_path = os.path.join(folder, f)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except:
                    pass

cleanup_old_files()


def update_task_status(task_id, status):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))

def add_reel_to_task(task_id, filename):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO task_reels (task_id, filename) VALUES (?, ?)", (task_id, filename))

def transcribe_audio(audio_path):
    segments, info = whisper_model.transcribe(audio_path, beam_size=5, language="ru")
    return " ".join([segment.text for segment in segments]).strip()

def download_video(url):
    filename = f"{uuid.uuid4()}.mp4"
    filepath = os.path.abspath(os.path.join(UPLOAD_FOLDER, filename))
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'outtmpl': filepath,
        'noplaylist': True,
        'quiet': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    # Ждем, пока файл реально появится и освободится
    for _ in range(10):
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            time.sleep(2) # Даем системе "продышаться"
            break
        time.sleep(1)
    return filepath

def process_single_reel(args):
    task_id, start, end, count, video_path, platforms, vk_data, music_files = args
    try:
        reel_filename = f"reel_{uuid.uuid4()}.mp4"
        reel_path = os.path.abspath(os.path.join(OUTPUT_FOLDER, reel_filename))
        
        clip = VideoFileClip(video_path)
        subclip = clip.subclipped(start, end)
        
        w, h = subclip.size
        target_w = h * (9/16)
        x1 = (w - target_w) / 2
        final_clip = subclip.cropped(x1=x1, y1=0, width=target_w, height=h)
        final_clip = final_clip.resized(new_size=(int(final_clip.w), int(final_clip.h)))
        
        temp_audio = f"temp_{uuid.uuid4()}.wav"
        subclip.audio.write_audiofile(temp_audio, logger=None)
        transcript = transcribe_audio(temp_audio)
        
        subclip.audio.close()
        try: os.remove(temp_audio)
        except: pass
        
        from uploader import generate_ai_content
        title, description = generate_ai_content(count + 1, context=transcript)
        
        try:
            part_text = TextClip(text=f"ЧАСТЬ {count + 1}", font_size=70, color='yellow', font='Arial-Bold', stroke_color='black', stroke_width=2).with_duration(final_clip.duration).with_position(('center', 80))
            display_text = transcript if transcript else title
            subtitle_text = TextClip(text=display_text, font_size=45, color='white', font='Arial-Bold', method='caption', size=(final_clip.w * 0.85, None), stroke_color='black', stroke_width=2).with_duration(final_clip.duration).with_position(('center', final_clip.h - 250))
            final_clip = CompositeVideoClip([final_clip, part_text, subtitle_text])
        except: pass

        if music_files:
            try:
                bg_music = AudioFileClip(random.choice(music_files)).subclipped(0, final_clip.duration).with_volume_scaled(0.1)
                final_clip = final_clip.with_audio(CompositeVideoClip([final_clip.audio, bg_music]).audio if final_clip.audio else bg_music)
            except: pass

        final_clip.write_videofile(reel_path, codec="libx264", audio_codec="aac", bitrate="5000k", logger=None, threads=4)
        
        if 'youtube' in platforms:
            upload_to_youtube(reel_path, count + 1, context=transcript)
        if 'instagram' in platforms:
            upload_to_instagram(reel_path, f"{title}\n\n{description}", INSTA_USERNAME, INSTA_PASSWORD)
        if 'vk' in platforms and vk_data:
            upload_to_vk(reel_path, title, description, vk_data['token'], vk_data['group_id'])
        
        add_reel_to_task(task_id, reel_filename)
        final_clip.close()
        subclip.close()
        clip.close()
        return True
    except Exception as e:
        print(f"Error processing reel {count+1}: {e}")
        return False

def process_video_task(task_id, url, platforms, vk_data):
    try:
        update_task_status(task_id, "Downloading...")
        video_path = download_video(url)
        
        update_task_status(task_id, "Processing Reels (Parallel)...")
        main_clip = VideoFileClip(video_path)
        duration = main_clip.duration
        main_clip.close()
        
        music_files = [os.path.join(MUSIC_FOLDER, f) for f in os.listdir(MUSIC_FOLDER) if f.endswith('.mp3')]
        
        reel_args = []
        count = 0
        for i in range(0, int(duration), 10):
            if i + 10 > duration or count >= 50: break
            reel_args.append((task_id, i, i + 10, count, video_path, platforms, vk_data, music_files))
            count += 1

        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.map(process_single_reel, reel_args)

        update_task_status(task_id, "Completed")
    except Exception as e:
        print(f"Task Error: {e}")
        update_task_status(task_id, f"Error: {str(e)}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url')
        platforms = request.form.getlist('platforms')
        vk_data = {'token': request.form.get('vk_token'), 'group_id': request.form.get('vk_group_id')} if 'vk' in platforms else None
        
        task_id = str(uuid.uuid4())
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO tasks (id, url, status, platforms, created_at) VALUES (?, ?, ?, ?, ?)",
                         (task_id, url, "Pending", ",".join(platforms), time.ctime()))
        
        threading.Thread(target=process_video_task, args=(task_id, url, platforms, vk_data)).start()
        return jsonify({"task_id": task_id})

    with sqlite3.connect(DB_PATH) as conn:
        tasks = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 10").fetchall()
        reels_data = {}
        for task in tasks:
            reels = conn.execute("SELECT filename FROM task_reels WHERE task_id = ?", (task[0],)).fetchall()
            reels_data[task[0]] = [r[0] for r in reels]
            
    return render_template('index.html', tasks=tasks, reels_data=reels_data)

@app.route('/api/tasks')
def api_tasks():
    with sqlite3.connect(DB_PATH) as conn:
        tasks = conn.execute("SELECT id, url, status, platforms, created_at FROM tasks ORDER BY created_at DESC LIMIT 20").fetchall()
        reels_data = {}
        for task in tasks:
            reels = conn.execute("SELECT filename FROM task_reels WHERE task_id = ?", (task[0],)).fetchall()
            reels_data[task[0]] = [r[0] for r in reels]
            
    tasks_list = [{"id": t[0], "url": t[1], "status": t[2], "platforms": t[3], "created_at": t[4]} for t in tasks]
    return jsonify({"tasks": tasks_list, "reels": reels_data})

@app.route('/delete_task/<task_id>', methods=['POST'])
def delete_task(task_id):
    with sqlite3.connect(DB_PATH) as conn:
        reels = conn.execute("SELECT filename FROM task_reels WHERE task_id = ?", (task_id,)).fetchall()
        for reel in reels:
            try: os.remove(os.path.join(OUTPUT_FOLDER, reel[0]))
            except: pass
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.execute("DELETE FROM task_reels WHERE task_id = ?", (task_id,))
    return jsonify({"status": "success"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
