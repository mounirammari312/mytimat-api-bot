from concurrent.futures import ThreadPoolExecutor
import json
import re
from urllib.parse import quote, unquote, urljoin, urlparse
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, request
import requests

# ==============================================================================
# 🛠️ إعدادات السيرفر الرئيسي (Vercel Serverless Entrypoint)
# ==============================================================================

app = Flask(__name__)

TMDB_API_KEY = '65687d1e167bc35f38ee0c88c3a37b74'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

TMDB_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

LARROZA_BASE_DOMAIN = 'https://larroza.mom'

# ==============================================================================
# 1. جلب دومين أكوام الشغال تلقائياً وتفكيك التشفير
# ==============================================================================

DIGITS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def base_encode(num, base):
  if num == 0:
    return DIGITS[0]
  res = []
  while num > 0:
    res.append(DIGITS[num % base])
    num //= base
  return ''.join(reversed(res))


def unpack_dean_edwards(script_text):
  pattern = r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\s*\(\s*'(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
  match = re.search(pattern, script_text, re.DOTALL)
  if not match:
    return script_text

  p, a_str, c_str, k_str = match.groups()
  a, c = int(a_str), int(c_str)
  k = k_str.split('|')

  for i in range(c - 1, -1, -1):
    symbol = base_encode(i, a)
    if i < len(k) and k[i]:
      p = re.sub(r'\b' + re.escape(symbol) + r'\b', k[i], p)
  return p


def safe_url(url):
  if not url:
    return url
  return quote(url, safe=':/?&=#%')


def get_active_akwam_domain():
  try:
    res = requests.get(
        'https://ak.sv/',
        headers=TMDB_HEADERS,
        timeout=3,
        allow_redirects=True,
    )
    parsed = urlparse(res.url)
    return f'{parsed.scheme}://{parsed.netloc}'
  except Exception:
    return 'https://akwam.it'


AKWAM_BASE_DOMAIN = get_active_akwam_domain()


def get_akwam_headers(referer_url=None):
  ref = safe_url(referer_url) if referer_url else f'{AKWAM_BASE_DOMAIN}/'
  return {
      'User-Agent': TMDB_HEADERS['User-Agent'],
      'Referer': ref,
  }


# ==============================================================================
# 2. تنسيق بطاقات أكوام و TMDB
# ==============================================================================


def format_poster(poster_path):
  return f'https://image.tmdb.org/t/p/w780{poster_path}' if poster_path else ''


def format_backdrop(backdrop_path):
  return (
      f'https://image.tmdb.org/t/p/w1280{backdrop_path}' if backdrop_path else ''
  )


def parse_akwam_cards(soup):
  card_containers = soup.select(
      'div.widget-body div.col-lg-2, div.widget-body div.col-md-3, '
      'div.entry-box'
  )
  items = []
  seen_urls = set()

  for card in card_containers:
    link_el = card.select_one('a[href*="/movie/"], a[href*="/series/"]')
    if not link_el:
      continue

    href = link_el['href']
    if not href.startswith('http'):
      href = f"{AKWAM_BASE_DOMAIN}/{href.lstrip('/')}"

    if href in seen_urls:
      continue
    seen_urls.add(href)

    title_el = card.select_one(
        'h3.entry-title, .entry-title, h3, a.entry-title'
    )
    img_el = card.select_one('img')

    title = 'غير متوفر'
    if title_el and title_el.get_text(strip=True):
      title = title_el.get_text(strip=True)
    elif img_el and img_el.get('alt'):
      title = img_el['alt']

    poster_url = ''
    if img_el:
      poster_url = (
          img_el.get('data-src') or img_el.get('data-lazy') or img_el.get('src')
      )
      if poster_url and 'placeholder.png' in poster_url:
        poster_url = img_el.get('data-src') or poster_url

    badge_els = card.select('span.badge, div.badge, span.quality')
    badges = [
        b.get_text(strip=True) for b in badge_els if b.get_text(strip=True)
    ]
    media_type = 'series' if '/series/' in href else 'movie'

    items.append({
        'id': href,
        'title': title,
        'original_title': title,
        'url': href,
        'poster': poster_url,
        'backdrop': poster_url,
        'tags': badges if badges else ['HD'],
        'rating': 0.0,
        'type': media_type,
    })

  return items


# ==============================================================================
# 3. محركات الكشط الاحتياطية للسيرفر (Fallback Scrapers - Timeout 3.5s)
# ==============================================================================


def fetch_akwam_stream(title, orig_title, media_type):
  search_queries = list(
      dict.fromkeys([q.strip() for q in [title, orig_title] if q and q.strip()])
  )
  try:
    card = None
    for q in search_queries:
      search_url = safe_url(f'{AKWAM_BASE_DOMAIN}/search?q={q}')
      search_res = requests.get(
          search_url, headers=get_akwam_headers(), timeout=3.5
      )
      soup = BeautifulSoup(search_res.text, 'html.parser')
      selector = (
          'a[href*="/movie/"]'
          if media_type == 'movie'
          else 'a[href*="/series/"]'
      )
      card = soup.select_one(selector)
      if card and card.get('href'):
        break

    if not card or not card.get('href'):
      return None

    item_url = card['href']
    if not item_url.startswith('http'):
      item_url = f"{AKWAM_BASE_DOMAIN}/{item_url.lstrip('/')}"

    target_url = item_url
    if media_type == 'tv':
      series_res = requests.get(
          safe_url(item_url),
          headers=get_akwam_headers(item_url),
          timeout=3.5,
      )
      soup_s = BeautifulSoup(series_res.text, 'html.parser')
      ep_card = soup_s.select_one('a[href*="/episode/"]')
      if ep_card and ep_card.get('href'):
        target_url = ep_card['href']
        if not target_url.startswith('http'):
          target_url = f"{AKWAM_BASE_DOMAIN}/{target_url.lstrip('/')}"

    res_target = requests.get(
        safe_url(target_url), headers=get_akwam_headers(target_url), timeout=3.5
    )
    soup_t = BeautifulSoup(res_target.text, 'html.parser')
    watch_btn = soup_t.select_one('a[href*="/watch/"], a.link-btn')

    if not watch_btn or not watch_btn.get('href'):
      return None

    watch_url = watch_btn['href']
    if not watch_url.startswith('http'):
      watch_url = f"{AKWAM_BASE_DOMAIN}/{watch_url.lstrip('/')}"

    res_w = requests.get(
        safe_url(watch_url), headers=get_akwam_headers(watch_url), timeout=3.5
    )
    raw_links = re.findall(
        r'https?://[^\s"\'<>]+\.(?:mp4)[^\s"\'<>]*', res_w.text
    )

    unique_links = []
    for link in raw_links:
      if link not in unique_links and '#Intent;' not in link:
        unique_links.append(link)

    qualities = []
    for idx, u in enumerate(unique_links):
      q_label = (
          '1080p FHD (أكوام)'
          if '1080' in u
          else ('720p HD (أكوام)' if '720' in u else '480p SD (أكوام)')
      )
      qualities.append({'quality': q_label, 'url': u, 'is_default': idx == 0})

    return qualities if qualities else None
  except Exception:
    return None


def fetch_larroza_stream(title, orig_title, host_url):
  search_queries = list(
      dict.fromkeys([q.strip() for q in [title, orig_title] if q and q.strip()])
  )
  headers = {
      'User-Agent': TMDB_HEADERS['User-Agent'],
      'Referer': f'{LARROZA_BASE_DOMAIN}/',
  }

  for query in search_queries:
    try:
      search_url = f'{LARROZA_BASE_DOMAIN}/search.php?keywords={quote(query)}'
      res_search = requests.get(search_url, headers=headers, timeout=3.5)
      soup_search = BeautifulSoup(res_search.text, 'html.parser')
      video_links = [
          a['href']
          for a in soup_search.find_all('a', href=True)
          if 'video.php' in a['href']
      ]
      if not video_links:
        continue

      embed_page_url = video_links[0].replace('video.php', 'embed.php')
      if not embed_page_url.startswith('http'):
        embed_page_url = urljoin(LARROZA_BASE_DOMAIN, embed_page_url)

      res_embed = requests.get(embed_page_url, headers=headers, timeout=3.5)
      soup_embed = BeautifulSoup(res_embed.text, 'html.parser')
      iframes = soup_embed.find_all('iframe')
      if not iframes:
        continue

      okhd_embed_url = iframes[0].get('src')
      if not okhd_embed_url.startswith('http'):
        okhd_embed_url = urljoin(embed_page_url, okhd_embed_url)

      emb_headers = {
          'User-Agent': TMDB_HEADERS['User-Agent'],
          'Referer': 'https://larroza.mom/',
      }
      res_okhd = requests.get(okhd_embed_url, headers=emb_headers, timeout=3.5)
      unpacked = unpack_dean_edwards(res_okhd.text)
      m3u8_matches = re.findall(
          r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked
      )

      if m3u8_matches:
        raw_stream = m3u8_matches[0]
        h_json = json.dumps({
            'User-Agent': TMDB_HEADERS['User-Agent'],
            'Referer': okhd_embed_url,
        })
        proxy_url = f'{host_url}hls-proxy?url={quote(raw_stream)}&headers={quote(h_json)}'
        return [{
            'quality': 'سيرفر لاروزا (HLS بروكسي)',
            'url': proxy_url,
            'is_default': True,
        }]
    except Exception:
      continue
  return None


# ==============================================================================
# 4. مسارات ה- API (Flask Routes)
# ==============================================================================


@app.route('/', methods=['GET'])
def index():
  return jsonify({
      'status': 'online',
      'mode': 'Hybrid Fast Backend',
      'active_domain': AKWAM_BASE_DOMAIN,
      'version': '4.0.0',
  })


@app.route('/hls-proxy', methods=['GET'])
def hls_proxy():
  target_url = request.args.get('url')
  headers_raw = request.args.get('headers', '{}')

  if not target_url:
    return 'Missing URL', 400

  target_url = unquote(target_url)
  try:
    headers_dict = json.loads(unquote(headers_raw))
  except Exception:
    headers_dict = {}

  try:
    resp = requests.get(
        target_url, headers=headers_dict, stream=True, timeout=8
    )
    content_type = resp.headers.get('Content-Type', '')

    if '.m3u8' in target_url.lower() or 'mpegurl' in content_type.lower():
      playlist_text = resp.text
      rewritten_lines = []

      for line in playlist_text.splitlines():
        line_str = line.strip()
        if line_str and not line_str.startswith('#'):
          segment_abs_url = urljoin(target_url, line_str)
          proxied_segment_url = f'/hls-proxy?url={quote(segment_abs_url)}&headers={quote(headers_raw)}'
          rewritten_lines.append(proxied_segment_url)
        else:
          rewritten_lines.append(line)

      return Response(
          '\n'.join(rewritten_lines),
          status=resp.status_code,
          content_type='application/vnd.apple.mpegurl',
      )
    else:

      def stream_gen():
        for chunk in resp.iter_content(chunk_size=64 * 1024):
          if chunk:
            yield chunk

      return Response(
          stream_gen(),
          status=resp.status_code,
          content_type=content_type or 'video/mp2t',
      )
  except Exception as e:
    return f'Proxy Error: {str(e)}', 500


@app.route('/api/home', methods=['GET'])
def get_home():
  try:
    movies_url = f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA'
    tv_url = (
        f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA'
    )

    m_res = requests.get(movies_url, headers=TMDB_HEADERS, timeout=4)
    t_res = requests.get(tv_url, headers=TMDB_HEADERS, timeout=4)

    trending_movies = []
    trending_tv = []

    if m_res.status_code == 200:
      trending_movies = [
          {
              'id': str(m.get('id', '')),
              'url': (
                  f"{AKWAM_BASE_DOMAIN}/search?q={quote(m.get('title') or m.get('original_title', ''))}"
              ),
              'title': m.get('title') or m.get('original_title', ''),
              'original_title': m.get('original_title', ''),
              'poster': format_poster(m.get('poster_path')),
              'backdrop': format_backdrop(
                  m.get('backdrop_path') or m.get('poster_path')
              ),
              'rating': round(m.get('vote_average', 0), 1),
              'tags': [
                  'TMDB',
                  (
                      str(m.get('release_date', '')[:4])
                      if m.get('release_date')
                      else '2026'
                  ),
              ],
              'type': 'movie',
          }
          for m in m_res.json().get('results', [])[:10]
          if m.get('poster_path')
      ]

    if t_res.status_code == 200:
      trending_tv = [
          {
              'id': str(t.get('id', '')),
              'url': (
                  f"{AKWAM_BASE_DOMAIN}/search?q={quote(t.get('name') or t.get('original_name', ''))}"
              ),
              'title': t.get('name') or t.get('original_name', ''),
              'original_title': t.get('original_name', ''),
              'poster': format_poster(t.get('poster_path')),
              'backdrop': format_backdrop(
                  t.get('backdrop_path') or t.get('poster_path')
              ),
              'rating': round(t.get('vote_average', 0), 1),
              'tags': [
                  'TMDB',
                  (
                      str(t.get('first_air_date', '')[:4])
                      if t.get('first_air_date')
                      else '2026'
                  ),
              ],
              'type': 'tv',
          }
          for t in t_res.json().get('results', [])[:10]
          if t.get('poster_path')
      ]

    return jsonify({
        'status': 'success',
        'data': [
            {
                'key': 'trending_movies',
                'title': '🔥 الأفلام الأكثر شهرة',
                'has_see_all': True,
                'see_all_params': {'type': 'movies', 'page': 1},
                'items': trending_movies,
            },
            {
                'key': 'trending_tv',
                'title': '📺 المسلسلات الأكثر مشاهدة',
                'has_see_all': True,
                'see_all_params': {'type': 'series', 'page': 1},
                'items': trending_tv,
            },
        ],
    })
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/catalog', methods=['GET'])
def get_catalog():
  cat_type = request.args.get('type', 'movies').lower()
  page = request.args.get('page', '1')

  catalog_url = safe_url(f'{AKWAM_BASE_DOMAIN}/{cat_type}?page={page}')

  try:
    res = requests.get(
        catalog_url, headers=get_akwam_headers(catalog_url), timeout=4
    )
    soup = BeautifulSoup(res.text, 'html.parser')
    items = parse_akwam_cards(soup)

    return jsonify({
        'status': 'success',
        'data': {
            'type': cat_type,
            'current_page': int(page),
            'items_count': len(items),
            'items': items,
        },
    })
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/search', methods=['GET'])
def search():
  query = request.args.get('q', '')
  if not query:
    return jsonify({'status': 'error', 'message': 'Query missing'}), 400

  try:
    search_url = f'{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={quote(query)}&language=ar-SA'
    res = requests.get(search_url, headers=TMDB_HEADERS, timeout=4).json()

    items = []
    for item in res.get('results', []):
      m_type = item.get('media_type')
      if m_type in ['movie', 'tv']:
        items.append({
            'id': str(item.get('id')),
            'url': (
                f"{AKWAM_BASE_DOMAIN}/search?q={quote(item.get('title') or item.get('name') or '')}"
            ),
            'title': (
                item.get('title')
                or item.get('name')
                or item.get('original_title')
            ),
            'original_title': item.get('original_title')
            or item.get('original_name')
            or '',
            'poster': format_poster(item.get('poster_path')),
            'backdrop': format_backdrop(
                item.get('backdrop_path') or item.get('poster_path')
            ),
            'rating': round(item.get('vote_average', 0), 1),
            'tags': ['TMDB'],
            'type': m_type,
        })

    return jsonify({'status': 'success', 'data': items})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/series-details', methods=['GET'])
def get_series_details():
  series_url = request.args.get('url', '')
  if not series_url:
    return jsonify({'status': 'error', 'message': 'Series URL missing'}), 400

  try:
    target_url = safe_url(series_url)
    res = requests.get(
        target_url, headers=get_akwam_headers(target_url), timeout=4
    )
    soup = BeautifulSoup(res.text, 'html.parser')

    season_links = soup.select('a[href*="/series/"]')
    seasons = []
    seen_seasons = set()
    for s in season_links:
      s_href = s['href']
      if not s_href.startswith('http'):
        s_href = f"{AKWAM_BASE_DOMAIN}/{s_href.lstrip('/')}"
      if s_href not in seen_seasons and s_href != series_url:
        seen_seasons.add(s_href)
        seasons.append({'title': s.get_text(strip=True) or 'موسم', 'url': s_href})

    episode_cards = soup.select('a[href*="/episode/"]')
    episodes = []
    seen_episodes = set()
    for ep in episode_cards:
      ep_href = ep['href']
      if not ep_href.startswith('http'):
        ep_href = f"{AKWAM_BASE_DOMAIN}/{ep_href.lstrip('/')}"
      if ep_href not in seen_episodes:
        seen_episodes.add(ep_href)
        episodes.append({'title': ep.get_text(strip=True), 'url': ep_href})

    return jsonify({
        'status': 'success',
        'data': {'seasons': seasons, 'episodes': episodes},
    })
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 🎬 نقطة جلب البث الاحتياطية (Fallback)
@app.route('/api/stream', methods=['GET'])
def get_direct_stream():
  title = request.args.get('title', '')
  orig_title = request.args.get('original_title', '')
  media_type = request.args.get('type', 'movie').lower()

  if not title and not orig_title:
    return jsonify({'status': 'error', 'message': 'Title missing'}), 400

  akwam_res = None
  larroza_res = None

  with ThreadPoolExecutor(max_workers=2) as executor:
    future_akwam = executor.submit(
        fetch_akwam_stream, title, orig_title, media_type
    )
    future_larroza = executor.submit(
        fetch_larroza_stream, title, orig_title, request.host_url
    )

    try:
      akwam_res = future_akwam.result(timeout=4)
    except Exception:
      pass

    try:
      larroza_res = future_larroza.result(timeout=4)
    except Exception:
      pass

  combined_streams = []
  if akwam_res:
    combined_streams.extend(akwam_res)
  if larroza_res:
    combined_streams.extend(larroza_res)

  if combined_streams:
    return jsonify({
        'status': 'success',
        'data': {
            'title': title or orig_title,
            'type': media_type,
            'active_domain': AKWAM_BASE_DOMAIN,
            'streams': combined_streams,
        },
    })

  return jsonify({'status': 'error', 'message': 'Content not found'}), 404


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)

