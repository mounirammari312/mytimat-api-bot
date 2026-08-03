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
  """دالة فك تشفير كود Dean Edwards Packed JS المخبأ"""
  try:
    pattern = (
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)"
    )
    match = re.search(pattern, packed_code, re.DOTALL)
    if not match:
      return ''

    payload, base_str, count_str, keywords_str = match.groups()
    base = int(base_str)
    count = int(count_str)
    keywords = keywords_str.split('|')

    def encode_base(num, b):
      chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
      if num < b:
        return chars[num]
      return encode_base(num // b, b) + chars[num % b]

    syms = {}
    for i in range(count):
      key = encode_base(i, base)
      val = keywords[i] if i < len(keywords) and keywords[i] else key
      syms[key] = val

    def replace_word(m):
      word = m.group(0)
      return syms.get(word, word)

    return re.sub(r'\b\w+\b', replace_word, payload)
  except Exception:
    return ''


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

    posts = soup.select('.block-post, li:has(div.imgSer)')
    for post in posts:
      a_tag = post.find('a', href=True)
      if not a_tag or 'vid=' not in a_tag['href']:
        continue

      vid = a_tag['href'].split('vid=')[-1]
      if vid in seen:
        continue
      seen.add(vid)

      title = (
          a_tag.get('title', '').strip()
          or (
              post.find('div', class_='title').get_text(strip=True)
              if post.find('div', class_='title')
              else ''
          )
      )

      poster = ''
      img_ser = post.find('div', class_='imgSer')
      if img_ser and img_ser.get('style'):
        match = re.search(r"url\(['\"]?(.*?)['\"]?\)", img_ser['style'])
        if match:
          poster = match.group(1)

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

  url = f'{BASE_URL}/search.php?keywords={query}'
  try:
    res = requests.get(url, headers=HEADERS, timeout=10)
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
        match = re.search(r"url\(['\"]?(.*?)['\"]?\)", img_ser['style'])
        if match:
          poster = match.group(1)

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

  url = f'{BASE_URL}/play.php?vid={vid}'
  try:
    res = requests.get(url, headers=HEADERS, timeout=10)
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


# 4️⃣ اقتناص رابط البث المباشر الذكي (Live Unpacked Stream Fetcher)
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
      embed_attr = srv.get('data-embed', '')
      match = re.search(r'src=["\']([^"\']+)["\']', embed_attr)
      embed_url = match.group(1) if match else ''

      if not embed_url or not embed_url.startswith('http'):
        continue

      try:
        srv_res = requests.get(
            embed_url, headers={'Referer': f'{BASE_URL}/'}, timeout=8
        )
        html_text = srv_res.text

        if 'File is no longer available' in html_text or srv_res.status_code != 200:
          continue

        # 1. البحث الصريح عن m3u8
        m3u8_matches = re.findall(
            r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', html_text
        )

        # 2. فك تشفير Packed JS عند الحاجة
        if not m3u8_matches and 'eval(function(p,a,c,k,e' in html_text:
          unpacked_text = unpack_js(html_text)
          m3u8_matches = re.findall(
              r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked_text
          )
          if not m3u8_matches:
            file_match = re.search(
                r'file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', unpacked_text
            )
            if file_match:
              m3u8_matches = [file_match.group(1)]

        if m3u8_matches:
          stream_url = list(set(m3u8_matches))[0]
          return jsonify({
              'status': 'success',
              'data': {
                  'stream_url': stream_url,
                  'headers': {
                      'Referer': embed_url,
                      'User-Agent': HEADERS['User-Agent'],
                  },
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

