import requests
import json
import re
from urllib.parse import quote
from flask import Flask, request, jsonify

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
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "Instagram Reel Scraper API"})


if __name__ == "__main__":
    # Run the Flask app
    app.run(debug=True, host='0.0.0.0', port=3400)