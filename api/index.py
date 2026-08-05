from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import requests

# ==============================================================================
# 🛠️ إعدادات التطبيق والسيرفر الرئيسي (Vercel Entrypoint)
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
# 1. اكتشاف دومين أكوام النشط تلقائياً
# ==============================================================================


def safe_url(url):
  return quote(url, safe=':/?&=#%') if url else url


def get_active_akwam_domain():
  """جلب النطاق النشط لموقع أكوام تلقائياً عبر رابط التوجيه ak.sv"""
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
    return 'https://akwam.site'


AKWAM_BASE_DOMAIN = get_active_akwam_domain()


def get_akwam_headers(referer_url=None):
  ref = safe_url(referer_url) if referer_url else f'{AKWAM_BASE_DOMAIN}/'
  return {
      'User-Agent': TMDB_HEADERS['User-Agent'],
      'Referer': ref,
  }


# ==============================================================================
# 2. دوال تنسيق بطاقات أكوام و TMDB
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
# 3. مسارات الـ API الكلية والكاملة (All Required Routes)
# ==============================================================================


@app.route('/', methods=['GET'])
def index():
  return jsonify({
      'status': 'online',
      'mode': 'JSON Rules Engine Full Backend',
      'active_domains': {
          'akwam': AKWAM_BASE_DOMAIN,
          'larroza': LARROZA_BASE_DOMAIN,
      },
      'version': '6.2.0',
  })


@app.route('/api/config', methods=['GET'])
def get_config():
  """تزويد التطبيق بجميع المواقع وقواعد الكشط الديناميكية لتحديث GenericScraper"""
  return jsonify({
      'status': 'success',
      'version': '6.2.0',
      'providers': [
          {
              'name': 'akwam',
              'domain': AKWAM_BASE_DOMAIN,
              'search_path': '/search?q={query}',
              'movie_selector': 'a[href*=/movie/]',
              'series_selector': 'a[href*=/series/]',
              'ep_selector': 'a[href*=/episode/]',
              'watch_selector': 'a[href*=/watch/], a.link-btn',
              'link_regex': r'https?://[^\s"\'<>]+\.(?:mp4)[^\s"\'<>]*',
              'requires_unpack': False,
          },
          {
              'name': 'larroza',
              'domain': LARROZA_BASE_DOMAIN,
              'search_path': '/search.php?keywords={query}',
              'card_selector': 'a[href*=video.php]',
              'iframe_selector': 'iframe',
              'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
              'requires_unpack': True,
          },



         {
              'name': 'moviz-time',
              'domain': 'https://moviz-time.site',
              'search_path': '/?s={query}',
              'card_selector': (
                  'a[href*="فيلم"], a[href*="مسلسل"], a[href*="/watch/"]'
              ),
              'watch_selector': 'iframe, [data-link], [data-url], [data-post]',
              'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
              'requires_unpack': True,   # 👈 احرص أن تكون الحروف الأولى كبيراً True
              'ajax_required': True,     # 👈 احرص أن تكون الحروف الأولى كبيراً True
          },
    







          
      ],
  })


@app.route('/api/home', methods=['GET'])
def get_home():
  """جلب القوائم الرئيسية للأفلام والمسلسلات"""
  try:
    trending_movies = []
    trending_tv = []

    try:
      movies_url = f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA'
      tv_url = (
          f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA'
      )

      m_res = requests.get(movies_url, headers=TMDB_HEADERS, timeout=4)
      t_res = requests.get(tv_url, headers=TMDB_HEADERS, timeout=4)

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
          timeout=4,
      )
      soup_m = BeautifulSoup(res_m.text, 'html.parser')
      trending_movies = parse_akwam_cards(soup_m)[:10]

    if not trending_tv:
      res_t = requests.get(
          f'{AKWAM_BASE_DOMAIN}/series',
          headers=get_akwam_headers(),
          timeout=4,
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
  """جلب قائمة الكتالوج وتصفح الأقسام والصفحات"""
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
        catalog_url, headers=get_akwam_headers(catalog_url), timeout=4
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
  """البحث في TMDB بالأسماء العربية والإنجليزي"""
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
  """جلب تفاصيل المسلسل وحلقات الموسم المحدد مع المعالجة الهجينة لمنع أخطاء 404"""
  series_url = request.args.get('url', '').strip()
  tmdb_id = request.args.get('id', '').strip()
  title = request.args.get('title', '').strip()
  orig_title = request.args.get('original_title', '').strip()
  selected_season = request.args.get('season', '1').strip()

  # استخراج معرف TMDB سواء تم تمريره في id أو url
  clean_tmdb_id = None
  if tmdb_id and tmdb_id.isdigit():
    clean_tmdb_id = tmdb_id
  elif series_url and series_url.isdigit():
    clean_tmdb_id = series_url

  # 1️⃣ المحاولة الأولى: إذا كان لدينا رابط مباشر لصفحة المسلسل في أكوام (يحتوي على /series/)
  if series_url and series_url.startswith('http') and '/series/' in series_url:
    try:
      target_url = safe_url(series_url)
      res = requests.get(
          target_url, headers=get_akwam_headers(target_url), timeout=4
      )
      if res.status_code == 200:
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
            seasons.append(
                {'title': s.get_text(strip=True) or 'موسم', 'url': s_href}
            )

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

        if episodes or seasons:
          return jsonify({
              'status': 'success',
              'data': {'seasons': seasons, 'episodes': episodes},
          })
    except Exception as e:
      print(f'⚠️ Akwam Direct Series Error: {e}')

  # 2️⃣ المحاولة الثانية: إذا كان الرابط رابط بحث، يتم استخراج الاسم والبحث عن صفحة المسلسل في أكوام
  search_term = title or orig_title
  if not search_term and '/search' in series_url and 'q=' in series_url:
    try:
      search_term = unquote(series_url.split('q=')[1].split('&')[0])
    except Exception:
      pass

  if search_term:
    try:
      search_req_url = f'{AKWAM_BASE_DOMAIN}/search?q={quote(search_term)}'
      res_search = requests.get(
          search_req_url, headers=get_akwam_headers(), timeout=4
      )
      if res_search.status_code == 200:
        soup_search = BeautifulSoup(res_search.text, 'html.parser')
        card = soup_search.select_one('a[href*="/series/"]')
        if card and card.get('href'):
          real_series_url = card['href']
          if not real_series_url.startswith('http'):
            real_series_url = (
                f"{AKWAM_BASE_DOMAIN}/{real_series_url.lstrip('/')}"
            )

          res_real = requests.get(
              safe_url(real_series_url),
              headers=get_akwam_headers(real_series_url),
              timeout=4,
          )
          soup_real = BeautifulSoup(res_real.text, 'html.parser')

          season_links = soup_real.select('a[href*="/series/"]')
          seasons = []
          seen_seasons = set()
          for s in season_links:
            s_href = s['href']
            if not s_href.startswith('http'):
              s_href = f"{AKWAM_BASE_DOMAIN}/{s_href.lstrip('/')}"
            if s_href not in seen_seasons and s_href != real_series_url:
              seen_seasons.add(s_href)
              seasons.append(
                  {'title': s.get_text(strip=True) or 'موسم', 'url': s_href}
              )

          episode_cards = soup_real.select('a[href*="/episode/"]')
          episodes = []
          seen_episodes = set()
          for ep in episode_cards:
            ep_href = ep['href']
            if not ep_href.startswith('http'):
              ep_href = f"{AKWAM_BASE_DOMAIN}/{ep_href.lstrip('/')}"
            if ep_href not in seen_episodes:
              seen_episodes.add(ep_href)
              episodes.append({'title': ep.get_text(strip=True), 'url': ep_href})

          if episodes or seasons:
            return jsonify({
                'status': 'success',
                'data': {'seasons': seasons, 'episodes': episodes},
            })
    except Exception as e:
      print(f'⚠️ Akwam Search Resolution Error: {e}')

  # 3️⃣ المحاولة الثالثة: جلب المواسم والحلقات رسمياً من TMDB API
  if clean_tmdb_id:
    try:
      tmdb_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}?api_key={TMDB_API_KEY}&language=ar-SA'
      res_tv = requests.get(tmdb_url, headers=TMDB_HEADERS, timeout=4).json()

      seasons = []
      for s in res_tv.get('seasons', []):
        s_num = s.get('season_number', 0)
        if s_num > 0:
          seasons.append({
              'season_number': s_num,
              'title': s.get('name') or f'الموسم {s_num}',
              'episode_count': s.get('episode_count', 0),
          })

      season_num = int(selected_season) if selected_season.isdigit() else 1

      ep_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}&language=ar-SA'
      res_ep = requests.get(ep_url, headers=TMDB_HEADERS, timeout=4).json()

      episodes = []
      for ep in res_ep.get('episodes', []):
        ep_num = ep.get('episode_number')
        episodes.append({
            'episode_number': ep_num,
            'title': f"الحلقة {ep_num} - {ep.get('name', '')}",
            'search_title': (
                f'{title} الموسم {season_num} الحلقة {ep_num}'
                if title
                else f'الموسم {season_num} الحلقة {ep_num}'
            ),
            'search_orig_title': (
                f'{orig_title} S{season_num:02d}E{ep_num:02d}'
                if orig_title
                else f'S{season_num:02d}E{ep_num:02d}'
            ),
        })

      return jsonify({
          'status': 'success',
          'data': {
              'current_season': season_num,
              'seasons': seasons,
              'episodes': episodes,
          },
      })
    except Exception as tmdb_err:
      print(f'⚠️ TMDB Series Season Switch Error: {tmdb_err}')

  # 4️⃣ الاستجابة الاحتياطية المضمونة بـ 200 OK لتفادي خطأ HTTP 404 في الأندرويد
  return jsonify({
      'status': 'success',
      'data': {'current_season': 1, 'seasons': [], 'episodes': []},
      'message': 'لم يتم العثور على حلقات لهذا المسلسل',
  })


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)

