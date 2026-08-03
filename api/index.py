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


# 4️⃣ اقتناص رابط البث المباشر المباشر (Live Stream Fetcher)
@app.route('/api/stream', methods=['GET'])
def get_stream():
  vid = request.args.get('vid', '')
  if not vid:
    return jsonify({'status': 'error', 'message': 'vid missing'}), 400

  play_url = f'{BASE_URL}/play.php?vid={vid}'
  try:
    res = requests.get(play_url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')

    srv_li = soup.select_one('li#server_Anafast') or soup.select_one(
        'li[id^="server_"]'
    )
    embed_url = ''
    if srv_li and srv_li.get('data-embed'):
      match = re.search(r'src=["\']([^"\']+)["\']', srv_li['data-embed'])
      if match:
        embed_url = match.group(1)

    if embed_url:
      srv_res = requests.get(
          embed_url, headers={'Referer': BASE_URL}, timeout=10
      )
      m3u8_matches = re.findall(
          r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', srv_res.text
      )

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

    return jsonify(
        {'status': 'error', 'message': 'Failed to extract stream link'}
    ), 404
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
  app.run(debug=True)
