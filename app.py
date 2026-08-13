from flask import Flask, render_template, request, send_file, after_this_request
import threading
import time
from pathlib import Path
import os
import subprocess
import json
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def home():
    url=None
    title=None
    duration=None
    thumbnail=None
    uploader= None
    views=None
    error= None

    
    if request.method == 'POST':
        url= request.form.get('url')
        if not url:
            error = "Please enter a valid YouTube URL."
        else:
            try:
                res = subprocess.run(['yt-dlp', '--dump-single-json', '--no-playlist', url], capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as e:
                print("Error occurred while fetching video info:", e.stderr)
                exit(1)
            data = json.loads(res.stdout)

            title = data.get('title')
            duration = format_duration(data.get('duration'))
            thumbnail = data.get('thumbnail')
            uploader = data.get('uploader')
            views = format_views(data.get('view_count'))


        

    return render_template('home.html', url=url, title=title, duration=duration, 
                           thumbnail=thumbnail, uploader=uploader, views=views, error=error)

@app.route('/formats', methods=['GET'])
def formats():
    url = request.args.get('url')
    if not url:
        return "No url provided", 400

    try:
        res = subprocess.run(['yt-dlp', '--dump-single-json', '--no-playlist', url], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print("Error occurred while fetching video info:", e.stderr)
        return "Error occurred while fetching video info", 500

    data = json.loads(res.stdout)
    formats = data.get('formats', [])
    video_formats = []
    audio_formats = []
    for fmt in formats:
        if fmt.get('vcodec') != 'none' and fmt.get('vcodec').startswith('avc1') and fmt.get('filesize') is not None and fmt.get('ext') == 'mp4':
            video_formats.append({
                'format_id': fmt.get('format_id'),
                'ext': fmt.get('ext'),
                'resolution': (fmt.get('resolution')).split('x')[1]+"p",
                'vcodec': fmt.get('vcodec'),
                'filesize': format_filesize(fmt.get('filesize')),
                'bitrate': int(fmt.get('tbr')),  
                'audiosize': estimate_audio_size(int(data.get('duration')), int(fmt.get('tbr')))

            })
        elif fmt.get('acodec') != 'none' and fmt.get('acodec').startswith('mp4a') and fmt.get('filesize') is not None:
            audio_formats.append({
                'format_id': fmt.get('format_id'),
                'ext': fmt.get('ext'),
                'acodec': fmt.get('acodec'),
                'filesize': format_filesize(fmt.get('filesize')),
                'bitrate': int(fmt.get('tbr')),  
                'audiosize': estimate_audio_size(int(data.get('duration')), int(fmt.get('tbr')))
            })

    

    return render_template('formats.html', video_formats=video_formats, audio_formats=audio_formats, url=url)

@app.route('/downloads', methods=['POST'])
def download():
    url = request.form.get('url', '').strip()
    format_id = request.form.get('format_id', '').strip()

    print(f"Received download request for URL: {url} with format_id: {format_id}", flush=True)

    if not url:
        return "No url provided", 400

    if not format_id:
        return "No format_id provided", 400

    os.makedirs('downloads', exist_ok=True)

    basedir = Path(__file__).resolve().parent
    ffmpeg_path = basedir / "ffmpeg" / "bin"
    download_path = basedir / "downloads"
    download_path.mkdir(exist_ok=True)
    before = set(os.listdir(download_path))

    template= str(download_path / "%(title)s.%(ext)s")

    audio_info = subprocess.run(["yt-dlp", "--no-playlist", "--dump-single-json", url], capture_output=True, text=True)

    if audio_info.returncode != 0:
        print("Error occurred while fetching audio info:", audio_info.stderr)
        return "Error occurred while fetching audio info", 500

    audio_data = json.loads(audio_info.stdout)

    best_audio= max([fmt for fmt in audio_data.get('formats', []) if fmt.get('acodec') != 'none' and fmt.get('vcodec')=='none' and fmt.get('format_id')], key=lambda fmt: fmt.get('abr') or 0)

    a_format_id = best_audio['format_id']
    res = subprocess.run(["yt-dlp", "--no-playlist","--ffmpeg-location", str(ffmpeg_path), "-f", f"{format_id}+{a_format_id}", "-o", template,"--merge-output-format", "mp4", "--print", "after_move:filepath", url], capture_output=True, text=True)

    if res.returncode != 0:
        print("Error occurred while downloading:", res.stderr)
        return "Error occurred while downloading", 500

    after = set(os.listdir(download_path))
    new_files = after - before

    if not new_files:
        print("Files currently in downloads:", os.listdir(download_path), flush=True)
        return "Downloaded file not found", 500

    filename = new_files.pop()
    filepath = download_path / filename

    print("Downloaded file path:", filepath, flush=True)
    print("File exists:", filepath.exists(), flush=True)

    response = send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

    def cleanup(response): 
        time.sleep(2)
        try: 
            os.remove(filepath) 
            print("Temporary file deleted:", filepath, flush=True) 
        except Exception as e: 
            print("Could not delete temporary file:", e, flush=True) 
        return response

    threading.Thread(target=cleanup, args=(filepath,)).start()

    return response

def format_duration(sec):
    if sec is None:
        return "Unknown"
    else:
        hours, remainder = divmod(sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}:{minutes:02}:{seconds:02}"
        else:
            return f"{minutes}:{seconds:02}"

def format_views(views):
    if views is None:
        return "Unknown"
    else:
        if views >= 1_000_000_000:
            return f"{views / 1_000_000_000:.1f}B"
        elif views >= 1_000_000:
            return f"{views / 1_000_000:.1f}M"
        elif views >= 1_000:
            return f"{views / 1_000:.1f}K"
        else:
            return str(views)

def format_filesize(size):
    if size is None:
        return "Unknown"
    else:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

def estimate_audio_size(duration, bitrate):
    if duration is None or bitrate is None:
        return "Unknown"
    else:
        # Convert duration from seconds to hours
        duration_hours = duration / 3600
        # Calculate size in MB
        size_mb = (duration_hours * bitrate) / 8  # Convert kbps to MB
        return f"{size_mb:.2f} MB"

if __name__ == '__main__':
    app.run(debug=True)