import json
import re
from urllib.parse import quote, unquote, urljoin
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, request
import requests

# استدعاء المحركات والوحدات المستقلة
from core.unpacker import unpack_dean_edwards
from scrapers.akwam import (
    AKWAM_BASE_DOMAIN,
    fetch_akwam_stream,
    format_backdrop,
    format_poster,
    get_akwam_headers,
    parse_akwam_cards,
    safe_url,
)
from scrapers.larroza import LARROZA_BASE_DOMAIN, fetch_larroza_stream

# ==============================================================================
# إعدادات التطبيق والسيرفر الرئيسي (Vercel Serverless Entrypoint)
# ==============================================================================

app = Flask(__name__)

TMDB_API_KEY = "65687d1e167bc35f38ee0c88c3a37b74"
TMDB_BASE_URL = "https://api.themoviedb.org/3"

TMDB_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}


# ==============================================================================
# مسارات ونقاط الـ API الكلية للتطبيق (Flask Routes)
# ==============================================================================


@app.route('/', methods=['GET'])
def index():
  return jsonify({
      'status': 'online',
      'engine': 'Modular Multi-Scraper Engine (Akwam + Larroza)',
      'active_akwam_domain': AKWAM_BASE_DOMAIN,
      'version': '3.0.0',
  })


@app.route('/hls-proxy', methods=['GET'])
def hls_proxy():
  """خادم البروكسي المركزي لتمرير الترويسات ومنع حظر HTTP 403 في ExoPlayer."""
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
        target_url, headers=headers_dict, stream=True, timeout=12
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
    trending_movies = []
    trending_tv = []

    try:
      movies_url = f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA'
      tv_url = (
          f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA'
      )

      m_res = requests.get(movies_url, headers=TMDB_HEADERS, timeout=6)
      t_res = requests.get(tv_url, headers=TMDB_HEADERS, timeout=6)

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
    except Exception as tmdb_err:
      print(f'⚠️ TMDB Fetch Exception: {tmdb_err}')

    if not trending_movies:
      res_m = requests.get(
          f'{AKWAM_BASE_DOMAIN}/movies',
          headers=get_akwam_headers(),
          timeout=6,
      )
      soup_m = BeautifulSoup(res_m.text, 'html.parser')
      trending_movies = parse_akwam_cards(soup_m)[:10]

    if not trending_tv:
      res_t = requests.get(
          f'{AKWAM_BASE_DOMAIN}/series',
          headers=get_akwam_headers(),
          timeout=6,
      )
      soup_t = BeautifulSoup(res_t.text, 'html.parser')
      trending_tv = parse_akwam_cards(soup_t)[:10]

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

  section = request.args.get('section', '')
  category = request.args.get('category', '')
  year = request.args.get('year', '')
  quality = request.args.get('quality', '')

  query_params = [f'page={page}']
  if section:
    query_params.append(f'section={section}')
  if category:
    query_params.append(f'category={category}')
  if year:
    query_params.append(f'year={year}')
  if quality:
    query_params.append(f'quality={quality}')

  query_string = '&'.join(query_params)
  catalog_url = safe_url(f'{AKWAM_BASE_DOMAIN}/{cat_type}?{query_string}')

  try:
    res = requests.get(
        catalog_url, headers=get_akwam_headers(catalog_url), timeout=8
    )
    soup = BeautifulSoup(res.text, 'html.parser')
    items = parse_akwam_cards(soup)

    page_links = soup.select('ul.pagination a, a.page-link')
    pages = [
        p.get_text(strip=True)
        for p in page_links
        if p.get_text(strip=True).isdigit()
    ]
    max_page = max(map(int, pages)) if pages else 1

    return jsonify({
        'status': 'success',
        'data': {
            'type': cat_type,
            'filters': {
                'section': section or 'all',
                'category': category or 'all',
                'year': year or 'all',
                'quality': quality or 'all',
            },
            'current_page': int(page),
            'total_pages': max_page,
            'has_next_page': int(page) < max_page,
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
    res = requests.get(search_url, headers=TMDB_HEADERS, timeout=8).json()

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
        target_url, headers=get_akwam_headers(target_url), timeout=8
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


@app.route('/api/stream', methods=['GET'])
def get_direct_stream():
  """نقطة جلب البث الذكية والمنسقة (المشغلات المضمنة OR أكوام OR لاروزا)."""
  embed_url = request.args.get('embed_url', '')
  title = request.args.get('title', '')
  orig_title = request.args.get('original_title', '')
  media_type = request.args.get('type', 'movie').lower()

  # 1. إذا تم تمرير embed_url مباشر
  if embed_url:
    try:
      emb_headers = {
          'User-Agent': TMDB_HEADERS['User-Agent'],
          'Referer': 'https://larroza.mom/',
      }
      res_emb = requests.get(embed_url, headers=emb_headers, timeout=8)
      unpacked_code = unpack_dean_edwards(res_emb.text)

      m3u8_links = re.findall(
          r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked_code
      )
      if m3u8_links:
        raw_stream = m3u8_links[0]
        h_json = json.dumps(
            {'User-Agent': TMDB_HEADERS['User-Agent'], 'Referer': embed_url}
        )
        proxy_url = f'{request.host_url}hls-proxy?url={quote(raw_stream)}&headers={quote(h_json)}'

        return jsonify({
            'status': 'success',
            'data': {
                'title': title or 'سيرفر مشغل مضمن',
                'type': media_type,
                'active_domain': AKWAM_BASE_DOMAIN,
                'streams': [{
                    'quality': 'سيرفر HLS فائق السرعة (عبر البروكسي)',
                    'url': proxy_url,
                    'is_default': True,
                }],
            },
        })
    except Exception as emb_err:
      print(f'⚠️ Embed processing exception: {emb_err}')

  if not title and not orig_title:
    return jsonify({'status': 'error', 'message': 'Title missing'}), 400

  # 2. المحاولة الأولى: كشط موقع أكوام
  akwam_streams = fetch_akwam_stream(title, orig_title, media_type)
  if akwam_streams:
    return jsonify({
        'status': 'success',
        'data': {
            'title': title,
            'type': media_type,
            'active_domain': AKWAM_BASE_DOMAIN,
            'streams': akwam_streams,
        },
    })

  # 3. المحاولة الثانية (Fallback): كشط موقع لاروزا
  larroza_streams = fetch_larroza_stream(title, orig_title, request.host_url)
  if larroza_streams:
    return jsonify({
        'status': 'success',
        'data': {
            'title': title,
            'type': media_type,
            'active_domain': LARROZA_BASE_DOMAIN,
            'streams': larroza_streams,
        },
    })

  return (
      jsonify(
          {'status': 'error', 'message': 'Content not found in Akwam or Larroza'}
      ),
      404,
  )


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)

