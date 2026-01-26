import requests
import json
import re
import os
import time
import tempfile
import logging
from urllib.parse import quote
from flask import Flask, request, jsonify, send_file
import yt_dlp
import asyncio
from deepgram import Deepgram
import bugsnag
from bugsnag.flask import handle_exceptions
from bugsnag.handlers import BugsnagHandler

def extract_shortcode_from_url(url):
    url = url.split('?')[0]
    pattern = r'instagram\.com/(?:[^/]+/)?(?:reel|p)/([^/?]+)'
    match = re.search(pattern, url)
    
    if not match:
        raise ValueError("Invalid Instagram URL")
    
    return match.group(1)


def create_payload(shortcode):
    variables = json.dumps({"shortcode": shortcode})
    encoded_variables = quote(variables)
    return f'variables={encoded_variables}&doc_id=24368985919464652'



def extract_reel_data(data):
    """Extract meaningful data from Instagram API response"""
    try:
        item = data['data']['xdt_api__v1__media__shortcode__web_info']['items'][0]
        
        # Extract video URLs (highest quality first)
        video_urls = []
        if 'video_versions' in item:
            # Sort by width (highest quality first)
            sorted_videos = sorted(item['video_versions'], key=lambda x: x.get('width', 0), reverse=True)
            video_urls = [video['url'] for video in sorted_videos]
        
        # Extract thumbnail URLs (highest quality first)
        thumbnail_urls = []
        if 'image_versions2' in item and 'candidates' in item['image_versions2']:
            # Sort by width (highest quality first)
            sorted_images = sorted(item['image_versions2']['candidates'], key=lambda x: x.get('width', 0), reverse=True)
            thumbnail_urls = [img['url'] for img in sorted_images]
        
        # Extract audio URL from extensions
        audio_url = None
        if 'extensions' in data and 'all_video_dash_prefetch_representations' in data['extensions']:
            for video_data in data['extensions']['all_video_dash_prefetch_representations']:
                for rep in video_data.get('representations', []):
                    if rep.get('mime_type') == 'audio/mp4':
                        audio_url = rep.get('base_url')
                        break
                if audio_url:
                    break
        
        # Extract user information
        user_info = {}
        if 'user' in item:
            user = item['user']
            user_info = {
                'id': user.get('pk'),
                'username': user.get('username'),
                'full_name': user.get('full_name'),
                'profile_pic_url': user.get('profile_pic_url'),
                'is_verified': user.get('is_verified', False),
                'is_private': user.get('is_private', False)
            }
        
        # Extract other meaningful details
        reel_info = {
            'shortcode': item.get('code'),
            'id': item.get('id'),
            'taken_at': item.get('taken_at'),
            'like_count': item.get('like_count'),
            'comment_count': item.get('comment_count'),
            'view_count': item.get('view_count', None),
            'has_audio': item.get('has_audio', False),
            'caption': item.get('caption', {}).get('text') if isinstance(item.get('caption'), dict) else None,
            'media_type': item.get('media_type'),
            'original_width': item.get('original_width'),
            'original_height': item.get('original_height'),
        }
        
        # Extract duration from video_dash_manifest if available
        if 'video_dash_manifest' in item:
            try:
                # Extracting media presentation duration
                import xml.etree.ElementTree as ET
                manifest = ET.fromstring(item['video_dash_manifest'])
                duration = manifest.attrib.get('mediaPresentationDuration')
                if duration:
                    reel_info['duration'] = duration
            except Exception as e:
                pass  # Handle parsing error gracefully

        # Extract clips metadata if available
        clips_metadata = {}
        if 'clips_metadata' in item:
            clips = item['clips_metadata']
            clips_metadata = clips
        
        # Extract other missing fields
        additional_info = {
            'is_paid_partnership': item.get('is_paid_partnership', False),
            'can_viewer_reshare': item.get('can_viewer_reshare', False),
            'comments_disabled': item.get('comments_disabled', False),
            'social_context': item.get('social_context', None),
            'fb_like_count': item.get('fb_like_count', None)
        }
        
        return {
            'success': True,
            'data': {
                'reel_info': reel_info,
                'user': user_info,
                'video_urls': video_urls,
                'thumbnail_urls': thumbnail_urls,
                'audio_url': audio_url,
                'clips_metadata': clips_metadata,
                **additional_info
            }
        }
        
    except Exception as e:
        return {"error": f"Failed to extract data: {str(e)}"}


def scrape_instagram_reel(url):
    try:
        shortcode = extract_shortcode_from_url(url)
        payload = create_payload(shortcode)


        headers = {
            'content-type': 'application/x-www-form-urlencoded',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'x-csrftoken': 'UNzTaJyJwVBCzd50o74UbpC7nrEdNWMd',
            'x-ig-app-id': '936619743392459',
        }

        response = requests.post(
            "https://www.instagram.com/graphql/query",
            headers=headers,
            data=payload,
            timeout=10
        )
        
        # Handle rate limiting
        if response.status_code == 429:
            return {"error": "Rate limited. Try again later."}
        
        # Handle not found
        if response.status_code == 404:
            return {"error": "Reel not found or private."}
        
        # Success
        if response.status_code == 200:
            data = response.json()
            
            print(data)
            # Save to file
            with open('res.json', 'w') as f:
                json.dump(data, f, indent=4)
            
            # Extract meaningful data
            return extract_reel_data(data)
    
    except requests.Timeout:
        return {"error": "Request timeout"}
    except Exception as e:
        return {"error": str(e)}



# Flask API
app = Flask(__name__)

# ---------------- Logging & Bugsnag configuration ----------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BUGSNAG_API_KEY = os.getenv("BUGSNAG_API_KEY")
if BUGSNAG_API_KEY:
    bugsnag.configure(
        api_key=BUGSNAG_API_KEY,
        project_root="insta-scrapper",
    )
    bugsnag_logger = logging.getLogger("test.logger")
    handler = BugsnagHandler()
    handler.setLevel(logging.ERROR)
    bugsnag_logger.addHandler(handler)
    handle_exceptions(app)
    logger.info("Bugsnag initialized and Flask exception handler attached.")
else:
    logger.warning("BUGSNAG_API_KEY not set; Bugsnag integration disabled.")


def notify_bugsnag(exc: Exception, video_url: str | None = None):
    """Send exception details to Bugsnag, including the video URL if available."""
    if not BUGSNAG_API_KEY:
        return
    try:
        meta_data = {}
        if video_url:
            meta_data["video"] = {"url": video_url}
        bugsnag.notify(exc, meta_data=meta_data if meta_data else None)
    except Exception:
        # Never let Bugsnag failures break the API
        pass

@app.route('/api/reel', methods=['POST'])
def get_reel_info():
    """POST API endpoint to extract reel information"""
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({"error": "Missing 'url' in request body"}), 400
        
        url = data['url']
        print("urlss", url)
        
        result = scrape_instagram_reel(url)
        
        if 'error' in result:
            return jsonify(result), 400
        
        return jsonify(result)
    
    except Exception as e:
        url = None
        try:
            body = request.get_json(silent=True) or {}
            url = body.get('url')
        except Exception:
            pass
        notify_bugsnag(e, video_url=url)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/bugsnag-test', methods=['GET'])
def bugsnag_test():
    raise RuntimeError("Bugsnag test exception")

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "Instagram Reel Scraper API"})


###############################
# YouTube extraction endpoints #
###############################

def _normalize_youtube_url(video_url: str) -> str:
    """Minimal helper to normalize Shorts URLs to watch URLs."""
    try:
        m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]+)", video_url)
        if m:
            video_id = m.group(1)
            return f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        return video_url
    return video_url


def _extract_youtube_metadata(url: str) -> dict:
    url = _normalize_youtube_url(url)
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "cookies": "www.youtube.com_cookies.txt"
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        duration = info.get("duration")
        title = info.get("title", "Unknown Title")
        thumbnail = info.get("thumbnail")
        video_id = info.get("id")

        return {
            "success": True,
            "videoId": video_id,
            "title": title,
            "duration": duration,
            "thumbnailUrl": thumbnail,
        }
    except yt_dlp.DownloadError as e:
        return {"success": False, "error": f"YouTube download error: {str(e)}", "error_code": "VIDEO_UNAVAILABLE"}
    except yt_dlp.ExtractorError as e:
        return {"success": False, "error": f"YouTube extractor error: {str(e)}", "error_code": "INVALID_URL"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}", "error_code": "UNEXPECTED_ERROR"}


def _download_youtube_audio(url: str) -> str:
    """Download audio as mp3 and return a path to the temp file."""
    url = _normalize_youtube_url(url)
    tmpdir = tempfile.mkdtemp(prefix="youtube_audio_")
    outtmpl = os.path.join(tmpdir, "audio.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "quiet": True,
        "socket_timeout": 60,
        "cookies": "www.youtube.com_cookies.txt"
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find resulting mp3
    for fname in os.listdir(tmpdir):
        if fname.endswith(".mp3"):
            return os.path.join(tmpdir, fname)
    raise RuntimeError("MP3 file not produced")


# ---------------- Deepgram transcription helpers ----------------
def _load_deepgram_api_keys() -> list[str]:
    keys: list[str] = []
    first = os.getenv("DEEPGRAM_API_KEY")
    if first:
        keys.append(first)
    for i in range(1, 10):
        v = os.getenv(f"DEEPGRAM_API_KEY_{i}")
        if v:
            keys.append(v)
    multi = os.getenv("DEEPGRAM_API_KEYS")
    if multi:
        import re as _re
        keys.extend([k.strip() for k in _re.split(r"[;,]", multi) if k.strip()])
    # dedup preserve order
    seen = set()
    dedup: list[str] = []
    for k in keys:
        if k and k not in seen:
            dedup.append(k)
            seen.add(k)
    return dedup


async def _dg_transcribe_file(audio_path: str, api_key: str) -> dict | None:
    try:
        dg = Deepgram(api_key)
        mimetype = "audio/mp3" if audio_path.endswith(".mp3") else "audio/wav" if audio_path.endswith(".wav") else "audio/mp3"
        with open(audio_path, "rb") as f:
            source = {"buffer": f, "mimetype": mimetype}
            resp = await dg.transcription.prerecorded(source, {"punctuate": True})
            return resp
    except Exception as e:
        print(f"Deepgram error: {e}")
        return None


def transcribe_audio_file(audio_path: str) -> str | None:
    keys = _load_deepgram_api_keys()
    if not keys:
        print("No Deepgram API keys configured")
        return None
    # try keys in order
    for idx, key in enumerate(keys):
        try:
            result = asyncio.run(_dg_transcribe_file(audio_path, key))
            if not result:
                continue
            # extract transcript text
            try:
                channels = result.get("results", {}).get("channels", [])
                if channels:
                    alts = channels[0].get("alternatives", [])
                    if alts and alts[0].get("transcript"):
                        txt = (alts[0].get("transcript") or "").strip()
                        if txt:
                            return txt
            except Exception:
                continue
        except Exception as e:
            print(f"Deepgram exception for key[{idx}]: {e}")
            continue
    return None


@app.route('/api/youtube/extract', methods=['POST'])
def youtube_extract():
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        if not url:
            return jsonify({"error": "Missing 'url' in request body"}), 400
        result = _extract_youtube_metadata(url)
        status = 200 if result.get("success") else 400
        return jsonify(result), status
    except Exception as e:
        notify_bugsnag(e, video_url=(data.get('url') if isinstance(data, dict) else None))
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/youtube/download-audio', methods=['POST'])
def youtube_download_audio():
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        if not url:
            return jsonify({"error": "Missing 'url' in request body"}), 400

        mp3_path = _download_youtube_audio(url)
        # For compatibility, still support direct audio download
        return send_file(mp3_path, mimetype='audio/mpeg', as_attachment=True,
                         download_name=f"youtube_audio_{int(time.time())}.mp3")
    except yt_dlp.DownloadError as e:
        notify_bugsnag(e, video_url=(data.get('url') if isinstance(data, dict) else None))
        return jsonify({"error": f"YouTube download error: {str(e)}"}), 400
    except Exception as e:
        notify_bugsnag(e, video_url=(data.get('url') if isinstance(data, dict) else None))
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/youtube/transcribe', methods=['POST'])
def youtube_transcribe():
    """Download audio and return transcript text using Deepgram keys from env."""
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        if not url:
            return jsonify({"error": "Missing 'url' in request body"}), 400

        mp3_path = _download_youtube_audio(url)
        transcript = transcribe_audio_file(mp3_path)
        try:
            if mp3_path and os.path.exists(mp3_path):
                os.remove(mp3_path)
        except Exception:
            pass

        if not transcript:
            return jsonify({"success": False, "error": "Transcription failed"}), 500
        return jsonify({"success": True, "transcript": transcript})
    except Exception as e:
        notify_bugsnag(e, video_url=(data.get('url') if isinstance(data, dict) else None))
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

if __name__ == "__main__":
    # Run the Flask app
    app.run(debug=True, host='0.0.0.0', port=3400)