import time
import json
import os
import hashlib
import requests
from googleapiclient.discovery import build
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import sys
import threading
import colorsys

CONFIG_FILE = "config.json"
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def setup_api_keys_gui():
    import webbrowser

    def open_url(url):
        webbrowser.open(url)

    def validate_keys(yt_key, lastfm_key, lastfm_secret):
        # Test YouTube key
        try:
            yt_service = build("youtube", "v3", developerKey=yt_key)
            yt_service.channels().list(part="snippet", id="UC_x5XG1OV2P6uZZ5FSM9Ttw").execute()
        except Exception as e:
            return False, f"Invalid YouTube API key or network error:\n{e}"
        # Test Last.fm key/secret
        try:
            resp = requests.get(
                "http://ws.audioscrobbler.com/2.0/",
                params={
                    "method": "track.getInfo",
                    "api_key": lastfm_key,
                    "artist": "Cher",
                    "track": "Believe",
                    "format": "json"
                }
            )
            if "error" in resp.json():
                raise Exception(resp.json()["message"])
        except Exception as e:
            return False, f"Invalid Last.fm API key/secret or network error:\n{e}"
        return True, ""

    class ApiKeyDialog(tk.Toplevel):
        def __init__(self, parent):
            super().__init__(parent)
            self.title("API Key Setup")
            self.resizable(False, False)
            self.grab_set()
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            self.result = None

            ttk.Label(self, text="YouTube Data v3 API Key:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
            yt_entry = ttk.Entry(self, width=50)
            yt_entry.grid(row=1, column=0, padx=10)
            yt_link = ttk.Label(self, text="Get key", foreground="blue", cursor="hand2")
            yt_link.grid(row=1, column=1, sticky="w")
            yt_link.bind("<Button-1>", lambda e: open_url("https://console.cloud.google.com/apis/credentials"))

            ttk.Label(self, text="Last.fm API Key:").grid(row=2, column=0, sticky="w", padx=10, pady=(10, 0))
            lastfm_entry = ttk.Entry(self, width=50)
            lastfm_entry.grid(row=3, column=0, padx=10)
            lastfm_link = ttk.Label(self, text="Get key", foreground="blue", cursor="hand2")
            lastfm_link.grid(row=3, column=1, sticky="w")
            lastfm_link.bind("<Button-1>", lambda e: open_url("https://www.last.fm/api/account/create"))

            ttk.Label(self, text="Last.fm API Secret:").grid(row=4, column=0, sticky="w", padx=10, pady=(10, 0))
            secret_entry = ttk.Entry(self, width=50, show="*")
            secret_entry.grid(row=5, column=0, padx=10)

            self.status = ttk.Label(self, text="", foreground="red")
            self.status.grid(row=6, column=0, columnspan=2, padx=10, pady=(5, 0))

            btn = ttk.Button(self, text="Save", command=self.on_save)
            btn.grid(row=7, column=0, columnspan=2, pady=15)

            self.entries = (yt_entry, lastfm_entry, secret_entry)

        def on_save(self):
            yt_key = self.entries[0].get().strip()
            lastfm_key = self.entries[1].get().strip()
            lastfm_secret = self.entries[2].get().strip()
            self.status.config(text="Validating keys, please wait...")
            self.update_idletasks()
            valid, msg = validate_keys(yt_key, lastfm_key, lastfm_secret)
            if valid:
                self.result = {
                    "YOUTUBE_API_KEY": yt_key,
                    "LASTFM_API_KEY": lastfm_key,
                    "LASTFM_API_SECRET": lastfm_secret
                }
                self.destroy()
            else:
                self.status.config(text=msg)

        def on_close(self):
            if messagebox.askokcancel("Quit", "API keys are required. Quit?"):
                self.result = None
                self.destroy()

    # Show dialog
    root = tk.Tk()
    root.withdraw()
    dialog = ApiKeyDialog(root)
    root.wait_window(dialog)
    root.destroy()
    if dialog.result:
        with open(CONFIG_FILE, "w") as f:
            json.dump(dialog.result, f)
        return dialog.result
    else:
        sys.exit("API key setup cancelled.")

def load_api_keys():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    else:
        while True:
            config = setup_api_keys_gui()
            if config:
                return config

def sanitize_filename(name):
    # Remove path separators and other dangerous characters
    return re.sub(r'[\\/:"*?<>|]+', "_", name)

def is_safe_path(path):
    # Prevent path traversal and absolute paths
    abs_path = os.path.abspath(path)
    return abs_path == os.path.normpath(abs_path) and '..' not in path

def cache_get_or_fetch(url, params):
    cache_key = hashlib.md5((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, cache_key + ".json")
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            return json.load(f)
    else:
        response = requests.get(url, params=params)
        data = response.json()
        with open(cache_path, "w") as f:
            json.dump(data, f)
        return data

def youtube_cache_fetch(service, request_func, params):
    key = f"youtube::{request_func.__name__}::{json.dumps(params, sort_keys=True)}"
    cache_key = hashlib.md5(key.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, cache_key + ".json")
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            return json.load(f)
    else:
        response = request_func(**params).execute()
        with open(cache_path, "w") as f:
            json.dump(response, f)
        return response

def get_playlist_items(playlist_id, api_key, last_fm_api_key, last_fm_api_secret, output_dir, playlist_title, progress_state, progress_callback=None, no_music=False):
    youtube = build('youtube', 'v3', developerKey=api_key)
    video_ids = []
    playlist_items = []
    next_page_token = None

    while True:
        try:
            params = {
                'part': 'snippet',
                'playlistId': playlist_id,
                'maxResults': 50,
                'pageToken': next_page_token
            }
            response = youtube_cache_fetch(youtube, youtube.playlistItems().list, params)
            video_ids.extend(item['snippet']['resourceId']['videoId'] for item in response.get('items', []))
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
        except Exception as e:
            print(f"Error fetching video IDs: {e}")
            break

    album_art_dir = os.path.join(output_dir, "album_art")
    os.makedirs(album_art_dir, exist_ok=True)
    total = len(video_ids)
    progress_state["start_time"] = time.time()
    for idx, video_id in enumerate(video_ids):
        try:
            params = {
                'part': 'snippet,contentDetails,statistics',
                'id': video_id
            }
            video_response = youtube_cache_fetch(youtube, youtube.videos().list, params)
            if video_response['items']:
                video_info = video_response['items'][0]
                video_title = video_info['snippet']['title']
                channel_title = video_info['snippet']['channelTitle']
                if " - topic" in channel_title.lower():
                    channel_title = channel_title.replace(" - topic", "").replace(" - Topic", "").replace(" - TOPIC", "")
                formatted_title = f"{video_title} - {channel_title}"
                video_url_short = f'https://youtu.be/{video_id}'
                video_url = f'https://www.youtube.com/watch?v={video_id}'

                tags = []
                album_art_relative_path = ""
                if not no_music:
                    params = {
                        "method": "track.getInfo",
                        "api_key": last_fm_api_key,
                        "artist": channel_title,
                        "track": video_title,
                        "format": "json"
                    }
                    try:
                        data = cache_get_or_fetch("http://ws.audioscrobbler.com/2.0/", params)
                        images = data.get("track", {}).get("album", {}).get("image", [])
                        if images:
                            large_image = next((img for img in reversed(images) if img.get("#text")), None)
                            if large_image:
                                album_art_url = large_image["#text"]
                                album_art_filename = os.path.basename(album_art_url)
                                safe_album_art_filename = sanitize_filename(album_art_filename)
                                album_art_path = os.path.join(album_art_dir, safe_album_art_filename)
                                if not os.path.exists(album_art_path):
                                    img_data = requests.get(album_art_url).content
                                album_art_relative_path = f"Assets/Squirt/playlists/{sanitize_filename(playlist_title)}/album_art/{safe_album_art_filename}".replace("\\", "/")
                        tag_data = data.get("track", {}).get("toptags", {}).get("tag", [])
                        tags = [tag["name"] for tag in tag_data if "name" in tag]
                    except Exception:
                        pass

                playlist_items.append({
                    "mainUrl": video_url,
                    "alternateUrl": video_url_short,
                    "title": formatted_title,
                    "description": "",
                    "tags": ", ".join(tags),
                    "image": album_art_relative_path
                })
            progress_state["current_title"] = video_title
            progress_state["current_idx"] = idx + 1
            progress_state["total"] = total
        except Exception as e:
            print(f"Error fetching video details: {e}")

        now = time.time()
        elapsed = now - progress_state["start_time"]
        done = idx + 1
        vps = done / elapsed if elapsed > 0 else 0
        remaining = total - done
        eta_sec = int(remaining / vps) if vps > 0 else 0
        eta_str = (
            f"{eta_sec//60}:{eta_sec%60:02d}" if eta_sec < 3600
            else f"{eta_sec//3600}:{(eta_sec%3600)//60:02d}:{eta_sec%60:02d}"
        )
        progress_state["vps"] = vps
        progress_state["eta"] = eta_str
        if progress_callback:
            progress_callback(done / total)
    return playlist_items

def create_json(playlist_title, playlist_items):
    return {
        "header": playlist_title,
        "entries": playlist_items
    }

def create_gui(YOUTUBE_API_KEY, LASTFM_API_KEY, LASTFM_API_SECRET):
    CANVAS_WIDTH = 600

    def browse_output():
        directory = filedialog.askdirectory()
        if directory:
            output_path.set(directory)
            check_ready()

    def check_ready(*args):
        if playlist_id.get().strip() and output_path.get().strip():
            if not status_label.winfo_ismapped():
                status_label.pack()
            status_label.config(text="Ready to convert")
            convert_btn.config(state="normal")
        else:
            if status_label.winfo_ismapped():
                status_label.pack_forget()
            convert_btn.config(state="disabled")

    root = tk.Tk()
    root.title("YouTube Playlist to ProTV Playlist Converter")
    root.geometry("640x250")
    root.resizable(False, False)

    playlist_id = tk.StringVar()
    output_path = tk.StringVar()
    playlist_id.trace_add("write", check_ready)
    output_path.trace_add("write", check_ready)

    main_frame = ttk.Frame(root, padding="20")
    main_frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(main_frame, text="YouTube Playlist ID:").pack(anchor=tk.W)
    ttk.Entry(main_frame, textvariable=playlist_id, width=65).pack(fill=tk.X, pady=(0, 10))
    ttk.Label(main_frame, text="Output Directory:").pack(anchor=tk.W)
    output_frame = ttk.Frame(main_frame)
    output_frame.pack(fill=tk.X, pady=(0, 10))
    ttk.Entry(output_frame, textvariable=output_path, width=55).pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Button(output_frame, text="Browse", command=browse_output).pack(side=tk.RIGHT, padx=(5, 0))

    no_music_mode = tk.BooleanVar(value=False)
    ttk.Checkbutton(main_frame, text="Non-music mode (skip Last.fm)", variable=no_music_mode).pack(anchor=tk.W, pady=(0, 10))

    status_label = ttk.Label(main_frame, text="Ready to convert")

    songinfo_canvas = tk.Canvas(main_frame, height=28, width=CANVAS_WIDTH, bg="black", highlightthickness=0)
    progress_canvas = tk.Canvas(main_frame, height=24, width=CANVAS_WIDTH, bg="black", highlightthickness=0)
    stats_canvas = tk.Canvas(main_frame, height=28, width=CANVAS_WIDTH, bg="black", highlightthickness=0)
    progress_state = {
        "progress": 0.0,
        "current_title": "",
        "current_idx": 0,
        "total": 0
    }

    def draw_songinfo_animated():
        songinfo_canvas.delete("all")
        now = time.time()
        title = progress_state.get("current_title", "")
        idx = progress_state.get("current_idx", 0)
        total = progress_state.get("total", 0)
        char_width = 13
        max_width = CANVAS_WIDTH - 20
        if title:
            base_str = f"{idx}/{total}   "
            available_chars = (max_width // char_width) - len(base_str)
            if available_chars < 4:
                display_title = ""
            elif len(title) > available_chars:
                display_title = title[:available_chars - 3] + "..."
            else:
                display_title = title
            info_str = base_str + display_title
        else:
            info_str = ""
        bar_x = 10
        info_y = 14
        for i, char in enumerate(info_str):
            hue = (i / max(1, len(info_str)) + now / 2) % 1.0
            r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1, 1)]
            color = f'#{r:02x}{g:02x}{b:02x}'
            songinfo_canvas.create_text(bar_x + i * char_width, info_y, text=char, fill=color, font=("Segoe UI", 12, "bold"), anchor="w")
        songinfo_canvas.after(50, draw_songinfo_animated)

    def draw_rainbow_bar_animated():
        progress = progress_state["progress"]
        width = CANVAS_WIDTH
        height = 24
        progress_canvas.delete("all")
        bar_width = int(width * progress)
        now = time.time()
        bar_x = 0
        for i in range(bar_width):
            hue = (i / width + now / 2) % 1.0
            r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1, 1)]
            color = f'#{r:02x}{g:02x}{b:02x}'
            progress_canvas.create_line(bar_x + i, 0, bar_x + i, height, fill=color)
        if bar_width < width:
            progress_canvas.create_rectangle(bar_x + bar_width, 0, bar_x + width, height, fill="#222", outline="#222")
        progress_canvas.after(50, draw_rainbow_bar_animated)

    def draw_stats_animated():
        width = CANVAS_WIDTH
        stats_canvas.delete("all")
        now = time.time()
        percent = int(progress_state.get("progress", 0.0) * 100)
        percent_str = f"{percent:3d}%"
        vps = progress_state.get("vps", 0.0)
        eta = progress_state.get("eta", "")
        stats_str = f"{percent_str}   {vps:.2f} videos/sec   ETA: {eta}"
        char_width = 13
        total_str_px = len(stats_str) * char_width
        bar_x = (width - total_str_px) // 2
        stats_y = 14
        for i, char in enumerate(stats_str):
            hue = (i / max(1, len(stats_str)) + now / 2) % 1.0
            r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1, 1)]
            color = f'#{r:02x}{g:02x}{b:02x}'
            stats_canvas.create_text(bar_x + i * char_width, stats_y, text=char, fill=color, font=("Segoe UI", 12, "bold"), anchor="w")
        stats_canvas.after(50, draw_stats_animated)

    def do_conversion(playlist, output):
        try:
            if not is_safe_path(output):
                raise ValueError("Unsafe output path detected.")

            status_label.config(text="Converting... Please wait...")
            root.update_idletasks()

            os.makedirs(output, exist_ok=True)
            youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
            params = {
                'part': 'snippet',
                'id': playlist
            }
            playlist_response = youtube_cache_fetch(youtube, youtube.playlists().list, params)
            playlist_title = playlist_response['items'][0]['snippet']['title']
            sanitized_title = sanitize_filename(playlist_title)

            progress_state["progress"] = 0.0

            playlist_items = get_playlist_items(
                playlist, YOUTUBE_API_KEY, LASTFM_API_KEY, 
                LASTFM_API_SECRET, output, playlist_title,
                progress_state,
                progress_callback=lambda p: progress_state.update(progress=p),
                no_music=no_music_mode.get()
            )
            playlist_json = create_json(playlist_title, playlist_items)

            json_path = os.path.join(output, sanitized_title + ".playlist")
            with open(json_path, "w") as f:
                json.dump(playlist_json, f, indent=4)

            progress_state["progress"] = 1.0

            root.after(0, lambda: status_label.config(text="Conversion completed successfully!"))
            def show_success_and_close():
                messagebox.showinfo("Success", f"Playlist converted and saved to:\n{json_path}")
                root.destroy()
            root.after(0, show_success_and_close)

        except Exception as e:
            err_msg = str(e)
            root.after(0, lambda: status_label.config(text="Error occurred during conversion"))
            root.after(0, lambda: messagebox.showerror("Error", f"An error occurred:\n{err_msg}"))

    def start_conversion():
        convert_btn.config(state="disabled")
        if not songinfo_canvas.winfo_ismapped():
            songinfo_canvas.pack(pady=(10, 0))
        if not progress_canvas.winfo_ismapped():
            progress_canvas.pack(pady=(0, 0))
        if not stats_canvas.winfo_ismapped():
            stats_canvas.pack(pady=(0, 10))
        root.geometry("640x400")
        status_label.config(text="Converting... Please wait...")
        playlist = playlist_id.get().strip()
        output = output_path.get().strip()
        threading.Thread(target=do_conversion, args=(playlist, output), daemon=True).start()

    convert_btn = ttk.Button(main_frame, text="Convert Playlist", command=start_conversion, state="disabled")
    convert_btn.pack(pady=20)

    # Add author credit at the bottom right, always visible
    author_label = ttk.Label(main_frame, text="Made by Squirticulous", font=("Segoe UI", 9, "italic"), foreground="gray")
    author_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-5)

    draw_songinfo_animated()
    draw_rainbow_bar_animated()
    draw_stats_animated()
    check_ready()
    return root

def main():
    config = load_api_keys()
    YOUTUBE_API_KEY = config["YOUTUBE_API_KEY"]
    LASTFM_API_KEY = config["LASTFM_API_KEY"]
    LASTFM_API_SECRET = config["LASTFM_API_SECRET"]

    import argparse
    parser = argparse.ArgumentParser(description="Generate a JSON playlist with Last.fm metadata from a YouTube playlist.")
    parser.add_argument("--playlist", help="YouTube playlist ID")
    parser.add_argument("--output", help="Output directory path")
    parser.add_argument("--no-music", action="store_true", help="Skip Last.fm and treat as generic video playlist")
    args = parser.parse_args()

    if args.playlist and args.output:
        playlist_id = args.playlist
        output_dir = args.output

        if not is_safe_path(output_dir):
            raise ValueError("Unsafe output path detected.")

        os.makedirs(output_dir, exist_ok=True)
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        params = {
            'part': 'snippet',
            'id': playlist_id
        }
        playlist_response = youtube_cache_fetch(youtube, youtube.playlists().list, params)
        playlist_title = playlist_response['items'][0]['snippet']['title']
        sanitized_title = sanitize_filename(playlist_title)
        progress_state = {"progress": 0.0}
        playlist_items = get_playlist_items(
            playlist_id, YOUTUBE_API_KEY, LASTFM_API_KEY, LASTFM_API_SECRET,
            output_dir, playlist_title, progress_state, no_music=args.no_music
        )
        playlist_json = create_json(playlist_title, playlist_items)
        json_path = os.path.join(output_dir, sanitized_title + ".playlist")
        with open(json_path, "w") as f:
            json.dump(playlist_json, f, indent=4)
        print("Done! JSON and album art (if found) are saved in:", output_dir)
    else:
        root = create_gui(YOUTUBE_API_KEY, LASTFM_API_KEY, LASTFM_API_SECRET)
        root.mainloop()

if __name__ == "__main__":
    main()