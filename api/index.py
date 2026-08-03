import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

app = Flask(__name__)

BASE_URL = "https://mycimatv.online"
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Referer': f'{BASE_URL}/',
}

# خريطة الأقسام والتصنيفات في الموقع
CATEGORIES = {
    'foreign_movies': {
        'title': '🎬 أفلام أجنبية',
        'url': f'{BASE_URL}/category.php?cat=ajnbe11',
    },
    'foreign_series': {
        'title': '📺 مسلسلات أجنبية',
        'url': f'{BASE_URL}/category.php?cat=Foreign-series-2025',
    },
    'turkish_series': {
        'title': '🇹🇷 مسلسلات تركية',
        'url': f'{BASE_URL}/category.php?cat=Turkish-series-2026',
    },
    'arabic_movies': {
        'title': '🔥 أفلام عربية',
        'url': f'{BASE_URL}/category.php?cat=aflam-arbe11',
    },
    'arabic_series': {
        'title': '🌙 مسلسلات عربية',
        'url': f'{BASE_URL}/category.php?cat=Arabic-TV-series-2026',
    },
}


def unpack_js(packed_code):
  """دالة فك تشفير كود Packed JS المخبأ"""
  try:
    pattern = (
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)"
    )
    match = re.search(pattern, packed_code, re.DOTALL)
    if not match:
      return ''

    payload, base_str, count_str, keywords_str = match.groups()
    base, count, keywords = (
        int(base_str),
        int(count_str),
        keywords_str.split('|'),
    )

    def encode_base(num, b):
      chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
      return (
          chars[num]
          if num < b
          else encode_base(num // b, b) + chars[num % b]
      )

    syms = {
        encode_base(i, base): (
            keywords[i]
            if i < len(keywords) and keywords[i]
            else encode_base(i, base)
        )
        for i in range(count)
    }
    return re.sub(
        r'\b\w+\b', lambda m: syms.get(m.group(0), m.group(0)), payload
    )
  except Exception:
    return ''


def scrape_category_items(url, limit=15):
  """دالة مساعدة لجلب العناصر من رابط قسم معين"""
  try:
    res = requests.get(url, headers=HEADERS, timeout=8)
    soup = BeautifulSoup(res.text, 'html.parser')
    items = []
    seen = set()

    for post in soup.select('.block-post, li:has(div.imgSer), a[href*="vid="]'):
      a_tag = post if post.name == 'a' else post.find('a', href=True)
      if not a_tag or 'vid=' not in a_tag.get('href', ''):
        continue

      vid = a_tag['href'].split('vid=')[-1]
      if vid in seen:
        continue

      title = a_tag.get('title', '').strip() or a_tag.get_text(strip=True)

      poster = ''
      if post.name != 'a':
        img_ser = post.find('div', class_='imgSer')
        if img_ser and img_ser.get('style'):
          m = re.search(r"url\(['\"]?(.*?)['\"]?\)", img_ser['style'])
          if m:
            poster = m.group(1)

      if not poster and post.find('img'):
        img = post.find('img')
        poster = img.get('src') or img.get('data-src') or ''

      if poster and not poster.startswith('http'):
        poster = f"{BASE_URL}/{poster.lstrip('/')}"

      if title and len(title) > 3 and 'صفحة' not in title:
        seen.add(vid)
        items.append({'vid': vid, 'title': title, 'poster': poster})
        if len(items) >= limit:
          break

    return items
  except Exception:
    return []


# 1️⃣ الواجهة الرئيسية بنمط نتفلكس وشاهد (Netflix/Shahid Home API)
@app.route('/api/home', methods=['GET'])
def get_home():
  try:
    sections = []

    for cat_key, cat_info in CATEGORIES.items():
      items = scrape_category_items(cat_info['url'], limit=15)
      if items:
        sections.append({
            'key': cat_key,
            'title': cat_info['title'],
            'items': items,
        })

    return jsonify({'status': 'success', 'data': sections})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 2️⃣ الكاتالوج الشامل مع دعم التصفح بالأقسام (?cat=foreign_movies)
@app.route('/api/catalog', methods=['GET'])
def get_catalog():
  page = request.args.get('page', '1')
  cat_key = request.args.get('cat', 'movies').lower()

  if cat_key in CATEGORIES:
    base_cat_url = CATEGORIES[cat_key]['url']
    url = (
        base_cat_url
        if page == '1'
        else f"{base_cat_url}&page={page}"
    )
  elif cat_key == 'series':
    url = (
        f'{BASE_URL}/all-series.php'
        if page == '1'
        else f'{BASE_URL}/all-series.php?page={page}'
    )
  else:
    url = (
        f'{BASE_URL}/'
        if page == '1'
        else f'{BASE_URL}/index.php?page={page}'
    )

  items = scrape_category_items(url, limit=30)
  return jsonify({'status': 'success', 'cat': cat_key, 'data': items})


# 3️⃣ البحث المباشر (Search)
@app.route('/api/search', methods=['GET'])
def search():
  query = request.args.get('q', '')
  if not query:
    return jsonify({'status': 'error', 'message': 'Query missing'}), 400
  try:
    url = f'{BASE_URL}/search.php?keywords={query}'
    items = scrape_category_items(url, limit=40)
    return jsonify({'status': 'success', 'data': items})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 4️⃣ التفاصيل والحلقات (Details & Episodes)
@app.route('/api/details', methods=['GET'])
def get_details():
  vid = request.args.get('vid', '')
  if not vid:
    return jsonify({'status': 'error', 'message': 'vid missing'}), 400
  try:
    res = requests.get(
        f'{BASE_URL}/play.php?vid={vid}', headers=HEADERS, timeout=10
    )
    soup = BeautifulSoup(res.text, 'html.parser')

    title_el = (
        soup.select_one('h1')
        or soup.select_one('.entry-title')
        or soup.select_one('title')
    )
    title = title_el.get_text(strip=True) if title_el else ''

    poster_el = soup.select_one('.poster img') or soup.select_one(
        'img[src*="uploads"]'
    )
    poster = (
        poster_el.get('src') or poster_el.get('data-src') if poster_el else ''
    )
    if poster and not poster.startswith('http'):
      poster = f"{BASE_URL}/{poster.lstrip('/')}"

    story_el = (
        soup.select_one('.story')
        or soup.select_one('.description')
        or soup.select_one('.entry-content')
    )
    story = story_el.get_text(strip=True) if story_el else ''

    episodes = []
    seen_vids = set()
    IGNORE_KEYWORDS = [
        'السابقة',
        'التالية',
        'الرئيسية',
        'صفحة',
        'فيس بوك',
        'تليجرام',
    ]

    for a in soup.find_all('a', href=True):
      href = a['href']
      ep_title = a.get_text(strip=True)

      if ('watch.php?vid=' in href or 'play.php?vid=' in href) and ep_title:
        ep_vid = href.split('vid=')[-1]
        if (
            ep_vid == vid
            or ep_vid in seen_vids
            or any(kw in ep_title for kw in IGNORE_KEYWORDS)
        ):
          continue

        seen_vids.add(ep_vid)
        episodes.append({'vid': ep_vid, 'title': ep_title})

    def get_episode_number(item):
      match = re.search(r'(?:الحلقة|حلقة)\s*(\d+)', item['title'])
      return int(match.group(1)) if match else 9999

    episodes.sort(key=get_episode_number)

    return jsonify({
        'status': 'success',
        'data': {
            'vid': vid,
            'title': title,
            'poster': poster,
            'story': story,
            'episodes': episodes,
        },
    })
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 5️⃣ اقتناص رابط البث المباشر (Multi-Server Stream Fetcher)
@app.route('/api/stream', methods=['GET'])
def get_stream():
  vid = request.args.get('vid', '')
  if not vid:
    return jsonify({'status': 'error', 'message': 'vid missing'}), 400

  play_url = f'{BASE_URL}/play.php?vid={vid}'
  try:
    res = requests.get(play_url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')

    servers = soup.select('li[id*="server"], li[data-embed]')

    def server_priority(s):
      sid = s.get('id', '').lower()
      if 'vidspeed' in sid or 'rty' in sid or 'vk' in sid or 'mp4' in sid:
        return 0
      return 1

    sorted_servers = sorted(servers, key=server_priority)

    for srv in sorted_servers:
      srv_id = srv.get('id', '').lower()
      if 'vidoba' in srv_id or 'filemoon' in srv_id or 'vidmoly' in srv_id:
        continue

      embed_attr = srv.get('data-embed', '')
      match = re.search(r'src=["\']([^"\']+)["\']', embed_attr)
      embed_url = match.group(1) if match else ''

      if not embed_url or not embed_url.startswith('http'):
        continue

      try:
        req_headers = {
            'User-Agent': HEADERS['User-Agent'],
            'Referer': embed_url,
        }
        srv_res = requests.get(
            embed_url,
            headers={
                'User-Agent': HEADERS['User-Agent'],
                'Referer': BASE_URL,
            },
            timeout=8,
        )
        html = srv_res.text

        if (
            'File is no longer available' in html
            or srv_res.status_code != 200
        ):
          continue

        if 'vk.com' in embed_url:
          vk_matches = re.findall(
              r'https?:\\/\\/[^\s"\'<>\\]+?\.(?:mp4|m3u8)[^\s"\'<>\\]*',
              html,
          )
          if vk_matches:
            clean_url = vk_matches[-1].replace('\\/', '/')
            return jsonify({
                'status': 'success',
                'data': {
                    'stream_url': clean_url,
                    'headers': {'User-Agent': HEADERS['User-Agent']},
                },
            })

        m3u8_matches = re.findall(
            r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', html
        )

        if not m3u8_matches and 'eval(function(p,a,c,k,e' in html:
          unpacked = unpack_js(html)
          m3u8_matches = re.findall(
              r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked
          )
          if not m3u8_matches:
            fm = re.search(
                r'file\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                unpacked,
            )
            if fm:
              m3u8_matches = [fm.group(1)]

        if m3u8_matches:
          stream_url = list(set(m3u8_matches))[0]
          return jsonify({
              'status': 'success',
              'data': {
                  'stream_url': stream_url,
                  'headers': req_headers,
              },
          })
      except Exception:
        continue

    return jsonify(
        {'status': 'error', 'message': 'Failed to extract stream link'}
    ), 404
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
  app.run(debug=True)

