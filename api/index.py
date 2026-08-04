import re
from urllib.parse import quote, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

# --- إعدادات TMDB API ---
TMDB_API_KEY = "15d2fd480251d4e1f31be9d76d471906"
TMDB_BASE_URL = "https://api.themoviedb.org/3"

TMDB_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}


# --- 1. دالة معالجة وتشفير الروابط العربية لمنع خطأ latin-1 / HTTP 500 ---
def safe_url(url):
  """تحويل الروابط التي تحتوي على حروف عربية إلى ترميز ASCII آمن للـ Headers"""
  if not url:
    return url
  return quote(url, safe=':/?&=#%')


# --- 2. الاكتشاف الديناميكي لنطاق أكوام النشط ---
def get_active_akwam_domain():
  try:
    res = requests.get(
        'https://ak.sv/',
        headers=TMDB_HEADERS,
        timeout=6,
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
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
          ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
      'Referer': ref,
  }


# --- 3. دوال معالجة وتحسين جودة الصور (HD Poster & Backdrop) ---
def format_poster(poster_path):
  """بوستر عمودي عالي الجودة للبطاقات (w780)"""
  return f'https://image.tmdb.org/t/p/w780{poster_path}' if poster_path else ''


def format_backdrop(backdrop_path):
  """غلاف أفقي عالي الجودة للسلايدر العلوي (w1280 HD)"""
  return (
      f'https://image.tmdb.org/t/p/w1280{backdrop_path}' if backdrop_path else ''
  )


# --- 4. محرك تشريح وتقشير بطاقات الكتالوج ---
def parse_akwam_cards(soup):
  card_containers = soup.select(
      'div.widget-body div.col-lg-2, div.widget-body div.col-md-3,'
      ' div.entry-box'
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
        'title': title,
        'url': href,
        'poster': poster_url,
        'backdrop': poster_url,  # احتياط في حال عدم وجود غلاف أفقي
        'tags': badges,
        'type': media_type,
    })

  return items


# --- نقاط الـ API المكتملة ---


# 🟢 أ) فحص الحالة العامة للسيرفر
@app.route('/', methods=['GET'])
def index():
  return jsonify({
      'status': 'online',
      'engine': 'Akwam Direct Scraping Engine',
      'active_domain': AKWAM_BASE_DOMAIN,
      'version': '1.4.0',
  })


# 🌐 ب) الشاشة الرئيسية الهجينة (دعم غلاف HD أفقي للسلايدر)
@app.route('/api/home', methods=['GET'])
def get_home():
  try:
    trending_movies = []
    trending_tv = []

    try:
      movies_url = f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA'
      tv_url = f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA'

      movies_res = requests.get(
          movies_url, headers=TMDB_HEADERS, timeout=5
      ).json()
      tv_res = requests.get(tv_url, headers=TMDB_HEADERS, timeout=5).json()

      trending_movies = [
          {
              'id': str(m.get('id')),
              'title': m.get('title') or m.get('original_title'),
              'poster': format_poster(m.get('poster_path')),
              'backdrop': format_backdrop(
                  m.get('backdrop_path') or m.get('poster_path')
              ),
              'rating': round(m.get('vote_average', 0), 1),
              'type': 'movie',
          }
          for m in movies_res.get('results', [])[:10]
          if m.get('poster_path')
      ]

      trending_tv = [
          {
              'id': str(t.get('id')),
              'title': t.get('name') or t.get('original_name'),
              'poster': format_poster(t.get('poster_path')),
              'backdrop': format_backdrop(
                  t.get('backdrop_path') or t.get('poster_path')
              ),
              'rating': round(t.get('vote_average', 0), 1),
              'type': 'tv',
          }
          for t in tv_res.get('results', [])[:10]
          if t.get('poster_path')
      ]
    except Exception as tmdb_err:
      print(f'⚠️ TMDB Fallback: {tmdb_err}')

    if not trending_movies:
      res_akwam = requests.get(
          f'{AKWAM_BASE_DOMAIN}/movies',
          headers=get_akwam_headers(),
          timeout=6,
      )
      soup = BeautifulSoup(res_akwam.text, 'html.parser')
      trending_movies = parse_akwam_cards(soup)[:10]

    if not trending_tv:
      res_akwam_tv = requests.get(
          f'{AKWAM_BASE_DOMAIN}/series',
          headers=get_akwam_headers(),
          timeout=6,
      )
      soup_tv = BeautifulSoup(res_akwam_tv.text, 'html.parser')
      trending_tv = parse_akwam_cards(soup_tv)[:10]

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


# 📂 ج) نقطة الكتالوج الشاملة (لزر "عرض الكل" والترقيم والفلترة)
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


# 🔍 د) البحث المباشر
@app.route('/api/search', methods=['GET'])
def search():
  query = request.args.get('q', '')
  if not query:
    return jsonify({'status': 'error', 'message': 'Query missing'}), 400

  try:
    search_url = f'{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={query}&language=ar-SA'
    res = requests.get(search_url, headers=TMDB_HEADERS, timeout=8).json()

    items = []
    for item in res.get('results', []):
      m_type = item.get('media_type')
      if m_type in ['movie', 'tv']:
        items.append({
            'id': str(item.get('id')),
            'title': (
                item.get('title')
                or item.get('name')
                or item.get('original_title')
            ),
            'poster': format_poster(item.get('poster_path')),
            'backdrop': format_backdrop(
                item.get('backdrop_path') or item.get('poster_path')
            ),
            'rating': round(item.get('vote_average', 0), 1),
            'type': m_type,
        })

    return jsonify({'status': 'success', 'data': items})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 🌀 هـ) تفاصيل المسلسل (المواسم والحلقات)
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


# 🎬 و) اقتناص روابط البث المباشرة (.mp4)
@app.route('/api/stream', methods=['GET'])
def get_direct_stream():
  title = request.args.get('title', '')
  media_type = request.args.get('type', 'movie').lower()

  if not title:
    return jsonify({'status': 'error', 'message': 'Title missing'}), 400

  try:
    search_url = safe_url(f'{AKWAM_BASE_DOMAIN}/search?q={title}')
    search_res = requests.get(
        search_url, headers=get_akwam_headers(), timeout=8
    )
    soup = BeautifulSoup(search_res.text, 'html.parser')

    selector = (
        'a[href*="/movie/"]' if media_type == 'movie' else 'a[href*="/series/"]'
    )
    card = soup.select_one(selector)

    if not card or not card.get('href'):
      return (
          jsonify(
              {'status': 'error', 'message': 'Content not found in engine'}
          ),
          404,
      )

    item_url = card['href']
    if not item_url.startswith('http'):
      item_url = f"{AKWAM_BASE_DOMAIN}/{item_url.lstrip('/')}"

    target_url = item_url
    if media_type == 'tv':
      series_res = requests.get(
          safe_url(item_url),
          headers=get_akwam_headers(item_url),
          timeout=8,
      )
      soup_s = BeautifulSoup(series_res.text, 'html.parser')
      ep_card = soup_s.select_one('a[href*="/episode/"]')
      if ep_card and ep_card.get('href'):
        target_url = ep_card['href']
        if not target_url.startswith('http'):
          target_url = f"{AKWAM_BASE_DOMAIN}/{target_url.lstrip('/')}"

    target_url = safe_url(target_url)
    res_target = requests.get(
        target_url, headers=get_akwam_headers(target_url), timeout=8
    )
    soup_t = BeautifulSoup(res_target.text, 'html.parser')
    watch_btn = soup_t.select_one('a[href*="/watch/"], a.link-btn')

    if not watch_btn or not watch_btn.get('href'):
      return (
          jsonify(
              {'status': 'error', 'message': 'Watch page link unavailable'}
          ),
          404,
      )

    watch_url = watch_btn['href']
    if not watch_url.startswith('http'):
      watch_url = f"{AKWAM_BASE_DOMAIN}/{watch_url.lstrip('/')}"

    watch_url = safe_url(watch_url)
    res_w = requests.get(
        watch_url, headers=get_akwam_headers(watch_url), timeout=8
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
      if '1080' in u:
        q_label = '1080p FHD'
      elif '720' in u:
        q_label = '720p HD'
      elif '480' in u:
        q_label = '480p SD'
      else:
        q_label = f'سيرفر مباشر {idx+1}'

      qualities.append({'quality': q_label, 'url': u, 'is_default': idx == 0})

    return jsonify({
        'status': 'success',
        'data': {
            'title': title,
            'type': media_type,
            'active_domain': AKWAM_BASE_DOMAIN,
            'streams': qualities,
        },
    })
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)

