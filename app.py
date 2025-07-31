
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, flash
import yt_dlp
import os
import urllib.parse
import tempfile
import shutil
from datetime import datetime
app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Optional: Needed for flashing messages
# Use the project directory for downloads to match where yt-dlp saves files
DOWNLOAD_DIR = os.path.abspath(os.path.dirname(__file__))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
# Clean up old files periodically
def cleanup_old_files():
    """Remove files older than 1 hour"""
    current_time = datetime.now()
    for filename in os.listdir(DOWNLOAD_DIR):
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.isfile(filepath):
            file_time = datetime.fromtimestamp(os.path.getctime(filepath))
            if (current_time - file_time).total_seconds() > 3600:  # 1 hour
                try:
                    os.remove(filepath)
                except:
                    pass
@app.route("/", methods=["GET", "POST"])
def index():
    video_url = ""
    title = ""
    resolutions = []
    error_msg = ""
    subtitles = []
    thumbnail_url = ""
    if request.method == "POST":
        video_url = request.form.get("url", "").strip()
        if not video_url:
            flash("Please enter a valid YouTube URL.", "error")
            return render_template("index.html", video_url="", title="", resolutions=[], error_msg="", thumbnail_url="")
        ydl_opts = {
            'quiet': True,
            'extract_flat': False,
            'no_warnings': True,
            'ignoreerrors': False,
            'cookiefile': None,  # For sites that need cookies
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            title = info.get("title", "Unknown Title")
            thumbnail_url = info.get("thumbnail", "")
            formats = info.get("formats", [])
            resolutions = []
            seen_format_ids = set()
            for f in formats:
                # Skip storyboards, thumbnails, and irrelevant formats
                ext = (f.get('ext') or '')
                format_id = (f.get('format_id') or '')
                vcodec = (f.get('vcodec') or '')
                acodec = (f.get('acodec') or '')
                height = f.get('height', 'Unknown')
                format_note = f.get('format_note', '')
                fps = f.get('fps')
                abr = f.get('abr')
                filesize = f.get('filesize')
                protocol = f.get('protocol', '')
                
                # Only include formats with a valid URL (truly downloadable)
                if not f.get('url'):
                    continue
                # Filter out manifest/streaming-only protocols
                if protocol in ['m3u8_native', 'm3u8', 'dash', 'http_dash_segments', 'https_dash_segments']:
                    continue
                # More lenient validation - only require format_id and ext
                if not format_id or not isinstance(format_id, str):
                    continue
                if not ext or not isinstance(ext, str):
                    continue
                if ext in ['mhtml', 'jpg', 'png'] or format_id.startswith('sb'):
                    continue
                if not format_id or format_id in seen_format_ids:
                    continue
                
                # Label type - handle missing codec info gracefully
                vcodec_available = vcodec and vcodec != 'none' and vcodec != 'None'
                acodec_available = acodec and acodec != 'none' and acodec != 'None'
                
                if vcodec_available and acodec_available:
                    fmt_type = 'video+audio'
                elif vcodec_available and not acodec_available:
                    fmt_type = 'video only (will merge with best audio)'
                elif not vcodec_available and acodec_available:
                    fmt_type = 'audio only'
                else:
                    # If we can't determine, assume it's a valid format
                    fmt_type = 'video+audio'
                
                # Build user-friendly label for dropdown
                container = ext.upper() if ext else ""
                fps_str = f" {fps}fps" if fps else ""
                filesize_str = f" ({filesize/1024/1024:.1f}MB)" if filesize else ""
                height_str = f"{height}p " if height and height != 'Unknown' else ""
                
                if fmt_type == 'video+audio':
                    label = f"{height_str}{container}{fps_str}{filesize_str} (Video+Audio)"
                elif fmt_type.startswith('video only'):
                    label = f"{height_str}{container}{fps_str}{filesize_str} (Video Only, will merge with best audio)"
                elif fmt_type == 'audio only':
                    abr_str = f"{abr}kbps " if abr else ""
                    label = f"{abr_str}{container}{filesize_str} (Audio Only)"
                else:
                    label = f"{height_str}{container}{fps_str}{filesize_str} (Universal Format)"
                
                resolutions.append({
                    'height': height,
                    'vcodec': vcodec,
                    'acodec': acodec,
                    'ext': ext,
                    'format_id': format_id,
                    'type': fmt_type,
                    'format_note': format_note,
                    'label': label,
                    'filesize': filesize
                })
                seen_format_ids.add(format_id)
            
            # Sort: video+audio first, then video only, then audio only, by height desc
            def sort_key(x):
                if x['type'].startswith('video+audio'):
                    return (2, x['height'] if isinstance(x['height'], int) else 0)
                elif x['type'].startswith('video only'):
                    return (1, x['height'] if isinstance(x['height'], int) else 0)
                elif x['type'].startswith('audio only'):
                    return (0, 0)
                else:
                    return (-1, 0)
            resolutions = sorted(resolutions, key=sort_key, reverse=True)
            # If no resolutions found, try to get basic format info
            if not resolutions:
                # Try to get at least one format for download
                basic_formats = []
                for f in formats:
                    if f.get('url') and f.get('format_id'):
                        basic_formats.append({
                            'height': f.get('height', 'Unknown'),
                            'vcodec': f.get('vcodec', 'unknown'),
                            'acodec': f.get('acodec', 'unknown'),
                            'ext': f.get('ext', 'mp4'),
                            'format_id': f.get('format_id'),
                            'type': 'universal',
                            'format_note': f.get('format_note', ''),
                            'label': f"Format {f.get('format_id')} ({f.get('ext', 'mp4').upper()})",
                            'filesize': f.get('filesize')
                        })
                        break  # Just get one basic format
                
                if basic_formats:
                    resolutions = basic_formats
                else:
                    flash("No downloadable video formats found. This video might be restricted or not supported.", "error")
            subtitles = []
            if 'subtitles' in info:
                for lang_code, tracks in info['subtitles'].items():
                    subtitles.append({'lang_code': lang_code, 'name': lang_code})
            if 'automatic_captions' in info:
                for lang_code, tracks in info['automatic_captions'].items():
                    if not any(s['lang_code'] == lang_code for s in subtitles):
                        subtitles.append({'lang_code': lang_code, 'name': lang_code + ' (auto)'})
        except Exception as e:
            error_msg = f"Failed to fetch video info: {str(e)}"
            # Add helpful tips for common social media issues
            if "linkedin" in video_url.lower():
                error_msg += " - LinkedIn videos might require authentication. Try copying the direct video URL."
            elif "facebook" in video_url.lower():
                error_msg += " - Facebook videos might be private. Ensure the video is publicly accessible."
            elif "instagram" in video_url.lower():
                error_msg += " - Instagram videos might be from private accounts. Try public posts only."
            flash(error_msg, "error")
    return render_template("index.html", video_url=video_url, title=title, resolutions=resolutions, error_msg=error_msg, subtitles=subtitles, thumbnail_url=thumbnail_url)

@app.route("/download", methods=["POST"])
def download():
    video_url = request.form.get("url", "").strip()
    format_id = request.form.get("format_id", "").strip()
    if not video_url or not format_id:
        flash("Missing video URL or format for download.", "error")
        return redirect(url_for("index"))
    # Clean up old files before download
    cleanup_old_files()
    try:
        # Defensive: Check that the selected format has all required fields
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl_check:
            info_dict = ydl_check.extract_info(video_url, download=False)
            available_format_ids = [f.get('format_id') for f in info_dict.get('formats', [])]
            selected_format = None
            if format_id == 'bestaudio':
                ydl_format = 'bestaudio'
                ext = 'mp3'  # or let yt-dlp decide
                vcodec = 'none'
                acodec = 'best'
            else:
                if format_id not in available_format_ids:
                    flash("The selected format is not available for this video. Please choose another.", "error")
                    return redirect(url_for("index"))
                for f in info_dict.get('formats', []):
                    if (f.get('format_id') or '') == format_id:
                        selected_format = f
                        break
                if not selected_format:
                    flash("Selected format not found in video info.", "error")
                    return redirect(url_for("index"))
                # Always treat as strings, default to empty string if missing
                ext = str(selected_format.get('ext') or '')
                vcodec = str(selected_format.get('vcodec') or '')
                acodec = str(selected_format.get('acodec') or '')
                
                # More flexible validation - allow formats with missing codec info
                if not ext or not isinstance(ext, str):
                    flash("Selected format is missing file extension. Please refresh and select a different format.", "error")
                    return redirect(url_for("index"))
                
                # Set default values for missing codecs
                if not vcodec or vcodec == 'none':
                    vcodec = 'none'
                if not acodec or acodec == 'none':
                    acodec = 'none'
        # Find all valid audio-only formats
        audio_only_formats = [
            f for f in info_dict.get('formats', [])
            if (f.get('vcodec') == 'none' and f.get('acodec') != 'none'
                and f.get('ext') and f.get('acodec') and f.get('url') and f.get('format_id'))
        ]
        # Set yt-dlp format string based on format type
        if format_id == 'bestaudio':
            # Already set above
            pass
        elif vcodec != 'none' and acodec != 'none':
            ydl_format = f"{format_id}"
        elif vcodec != 'none' and acodec == 'none':
            if not audio_only_formats:
                # Try to use the format anyway - yt-dlp might handle it
                ydl_format = f"{format_id}"
            else:
                best_audio = audio_only_formats[0]
                # More lenient audio format validation
                if best_audio.get('format_id'):
                    audio_format_id = best_audio.get('format_id')
                    ydl_format = f"{format_id}+{audio_format_id}"
                else:
                    ydl_format = f"{format_id}"
        elif vcodec == 'none' and acodec != 'none':
            flash("Please use the 'Download Audio Only' button for audio formats.", "error")
            return redirect(url_for("index"))
        else:
            # For unknown formats, try to use them directly
            ydl_format = f"{format_id}"
        ydl_opts = {
            'format': ydl_format,
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'noplaylist': True,
            'no_warnings': True,
            'ignoreerrors': False,
            'extract_flat': False,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Check for empty or malformed ydl_format
        if not ydl_format or not isinstance(ydl_format, str):
            flash("Internal error: Download format is invalid. Please try a different format.", "error")
            return redirect(url_for("index"))
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=True)
                filename = ydl.prepare_filename(info)
                # Ensure output is .mp4
                if filename.endswith((".webm", ".mkv")):
                    new_filename = filename.rsplit(".", 1)[0] + ".mp4"
                    # Rename the file if it exists
                    if os.path.exists(filename):
                        os.rename(filename, new_filename)
                    filename = new_filename
            except Exception as download_error:
                flash(f"Download failed: {str(download_error)}. The selected format might not be available. Please try a different format.", "error")
                return redirect(url_for("index"))
        # Get the actual filename from the downloaded file
        if os.path.exists(filename):
            basename = os.path.basename(filename)
            # Safely encode the filename for the redirect URL
            safe_basename = urllib.parse.quote(basename)
            return redirect(url_for("downloaded", filename=safe_basename))
        else:
            # If file doesn't exist, try to find it in DOWNLOAD_DIR
            actual_files = [f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))]
            if actual_files:
                # Get the most recent file
                actual_files.sort(key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_DIR, x)), reverse=True)
                latest_file = actual_files[0]
                safe_basename = urllib.parse.quote(latest_file)
                return redirect(url_for("downloaded", filename=safe_basename))
            else:
                flash("Download completed but file not found.", "error")
                return redirect(url_for("index"))
    except Exception as e:
        flash(f"Download failed: {str(e)}. This may be because the selected format is no longer available. Please refresh the available resolutions and try again.", "error")
        return redirect(url_for("index"))

@app.route("/download_subtitle", methods=["POST"])
def download_subtitle():
    video_url = request.form.get("url", "").strip()
    lang_code = request.form.get("lang_code", "").strip()
    sub_format = request.form.get("sub_format", "srt").strip()
    if not video_url or not lang_code:
        flash("Missing video URL or subtitle language.", "error")
        return redirect(url_for("index"))
    try:
        ydl_opts = {
            'writesubtitles': True,
            'subtitleslangs': [lang_code],
            'skip_download': True,
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'noplaylist': True,
            'subtitlesformat': sub_format,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            # Find the generated subtitle file
            title = info.get('title', 'subtitle')
            subtitle_file = os.path.join(DOWNLOAD_DIR, f"{title}.{lang_code}.{sub_format}")
            if not os.path.exists(subtitle_file):
                # Try fallback
                subtitle_file = os.path.join(DOWNLOAD_DIR, f"{title}.{sub_format}")
            if not os.path.exists(subtitle_file):
                flash("Subtitle file not found after download.", "error")
                return redirect(url_for("index"))
        return send_from_directory(DOWNLOAD_DIR, os.path.basename(subtitle_file), as_attachment=True)
    except Exception as e:
        flash(f"Subtitle download failed: {str(e)}", "error")
        return redirect(url_for("index"))

@app.route("/downloads/<path:filename>")
def downloaded(filename):
    try:
        # Decode the filename for serving
        from urllib.parse import unquote
        decoded_filename = unquote(filename)
        
        # Ensure the file exists
        file_path = os.path.join(DOWNLOAD_DIR, decoded_filename)
        if not os.path.exists(file_path):
            flash("Downloaded file not found.", "error")
            return redirect(url_for("index"))
            
        return send_from_directory(DOWNLOAD_DIR, decoded_filename, as_attachment=True)
    except Exception as e:
        flash(f"Error serving file: {str(e)}", "error")
        return redirect(url_for("index"))
#if __name__ == "__main__":
#    app.run(host="0.0.0.0", port=8585, debug=True)

def progress_hook(d):
    if d['status'] == 'downloading':
        print(f"Downloading: {d.get('_percent_str', '0%')} of {d.get('_total_bytes_str', 'Unknown')}")
    elif d['status'] == 'finished':
        print(f"Download finished, now converting...")
# Define the format
ydl_format = 'bestvideo+bestaudio/best'
# Then in your ydl_opts:
ydl_opts = {
    'format': ydl_format,
    'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
    'quiet': False,  # Change to False to see output
    'cookiefile': 'linkedin_cookies.txt',  # ← Add this line
    'noplaylist': True,
    'no_warnings': False,  # Change to False
    'ignoreerrors': False,
    'extract_flat': False,
    'progress_hooks': [progress_hook],
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
