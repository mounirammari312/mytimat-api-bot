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


def extract_stream_from_embed(embed_url):
  """استخراج رابط البث من مختلف خوادم المشاهدة"""
  try:
    req_headers = {'User-Agent': HEADERS['User-Agent'], 'Referer': embed_url}
    res = requests.get(
        embed_url,
        headers={'User-Agent': HEADERS['User-Agent'], 'Referer': BASE_URL},
        timeout=8,
    )
    html = res.text

    if 'File is no longer available' in html or res.status_code != 200:
      return None, None

    # 1. دعم سيرفرات VK (vk.com)
    if 'vk.com' in embed_url:
      vk_matches = re.findall(
          r'https?:\\/\\/[^\s"\'<>\\]+?\.(?:mp4|m3u8)[^\s"\'<>\\]*', html
      )
      if not vk_matches:
        vk_matches = re.findall(
            r'https?://[^\s"\'<>]+?\.(?:mp4|m3u8)[^\s"\'<>]*', html
        )
      if vk_matches:
        clean_url = vk_matches[-1].replace('\\/', '/')
        return clean_url, {'User-Agent': HEADERS['User-Agent']}

    # 2. البحث الصريح عن m3u8 أو mp4
    m3u8_matches = re.findall(
        r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', html
    )

    # 3. فك تشفير Packed JS (مثل Rty1 / Mp4 / Ok / Larhu)
    if not m3u8_matches and 'eval(function(p,a,c,k,e' in html:
      unpacked = unpack_js(html)
      m3u8_matches = re.findall(
          r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked
      )
      if not m3u8_matches:
        fm = re.search(
            r'file\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', unpacked
        )
        if fm:
          m3u8_matches = [fm.group(1)]

    if m3u8_matches:
      stream_url = list(set(m3u8_matches))[0]
      return stream_url, req_headers

  except Exception:
    pass

  return None, None


# 1️⃣ القائمة الرئيسية (Catalog)
@app.route('/api/catalog', methods=['GET'])
def get_catalog():
  page = request.args.get('page', '1')
  url = (
      f'{BASE_URL}/'
      if page == '1'
      else f'{BASE_URL}/index.php?page={page}'
  )
  try:
    res = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')
    items = []
    seen = set()

    for post in soup.select('.block-post, li:has(div.imgSer)'):
      a_tag = post.find('a', href=True)
      if not a_tag or 'vid=' not in a_tag['href']:
        continue
      vid = a_tag['href'].split('vid=')[-1]
      if vid in seen:
        continue
      seen.add(vid)

      title = a_tag.get('title', '').strip() or (
          post.find('div', class_='title').get_text(strip=True)
          if post.find('div', class_='title')
          else ''
      )
      poster = ''
      img_ser = post.find('div', class_='imgSer')
      if img_ser and img_ser.get('style'):
        m = re.search(r"url\(['\"]?(.*?)['\"]?\)", img_ser['style'])
        if m:
          poster = m.group(1)

      if poster and not poster.startswith('http'):
        poster = f'{BASE_URL}/{poster}'
      if title:
        items.append({'vid': vid, 'title': title, 'poster': poster})

    return jsonify({'status': 'success', 'data': items})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 2️⃣ البحث المباشر (Search)
@app.route('/api/search', methods=['GET'])
def search():
  query = request.args.get('q', '')
  if not query:
    return jsonify({'status': 'error', 'message': 'Query missing'}), 400
  try:
    res = requests.get(
        f'{BASE_URL}/search.php?keywords={query}', headers=HEADERS, timeout=10
    )
    soup = BeautifulSoup(res.text, 'html.parser')
    items = []
    seen = set()

    for a in soup.find_all('a', href=lambda h: h and 'vid=' in h):
      vid = a['href'].split('vid=')[-1]
      if vid in seen:
        continue
      title = a.get('title', '').strip() or a.get_text(strip=True)
      container = (
          a.find_parent(class_=re.compile(r'block|item|thumb|video|post'))
          or a.parent
          or a
      )

      poster = ''
      img_ser = container.find('div', class_='imgSer') or a.find(
          'div', class_='imgSer'
      )
      if img_ser and img_ser.get('style'):
        m = re.search(r"url\(['\"]?(.*?)['\"]?\)", img_ser['style'])
        if m:
          poster = m.group(1)
      if not poster:
        img = container.find('img') or a.find('img')
        if img:
          poster = img.get('src') or img.get('data-src') or ''

      if poster and not poster.startswith('http'):
        poster = f'{BASE_URL}/{poster}'

      if title and len(title) > 3 and 'صفحة' not in title:
        seen.add(vid)
        items.append({'vid': vid, 'title': title, 'poster': poster})

    return jsonify({'status': 'success', 'data': items})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 3️⃣ التفاصيل والحلقات (Details & Episodes)
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
      poster = f'{BASE_URL}/{poster}'

    story_el = (
        soup.select_one('.story')
        or soup.select_one('.description')
        or soup.select_one('.entry-content')
    )
    story = story_el.get_text(strip=True) if story_el else ''

    episodes = []
    seen_vids = set()
    for a in soup.find_all('a', href=True):
      href = a['href']
      ep_title = a.get_text(strip=True)
      if 'watch.php?vid=' in href and ep_title:
        ep_vid = href.split('vid=')[-1]
        if ep_vid not in seen_vids:
          seen_vids.add(ep_vid)
          episodes.append({'vid': ep_vid, 'title': ep_title})

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


# 4️⃣ اقتناص رابط البث الشامل (Multi-Server Stream Fetcher)
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

    for srv in servers:
      srv_id = srv.get('id', '').lower()
      if 'vidoba' in srv_id:
        continue  # تجاوز سيرفر Vidoba بسبب قيود الـ IP

      embed_attr = srv.get('data-embed', '')
      match = re.search(r'src=["\']([^"\']+)["\']', embed_attr)
      embed_url = match.group(1) if match else ''

      if not embed_url or not embed_url.startswith('http'):
        continue

      stream_url, req_headers = extract_stream_from_embed(embed_url)

      if stream_url:
        return jsonify({
            'status': 'success',
            'data': {
                'stream_url': stream_url,
                'headers': req_headers,
            },
        })

    return jsonify(
        {'status': 'error', 'message': 'Failed to extract stream link'}
    ), 404
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
  app.run(debug=True)

