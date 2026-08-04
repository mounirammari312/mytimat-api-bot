import re
from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import requests

# ==============================================================================
# إعدادات التطبيق والسيرفر الرئيسي
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
# 1. أدوات الأمان والاكتشاف الديناميكي للنطاقات (Dynamic Resolvers)
# ==============================================================================


def safe_url(url):
  if not url:
    return url
  return quote(url, safe=':/?&=#%')


def get_active_akwam_domain():
  try:
    res = requests.get(
        'https://ak.sv/',
        headers=TMDB_HEADERS,
        timeout=5,
        allow_redirects=True,
    )
    parsed = urlparse(res.url)
    return f'{parsed.scheme}://{parsed.netloc}'
  except Exception:
    return 'https://akwam.it'


def get_active_arabseed_domain():
  domains = [
      'https://arabseed.store',
      'https://arabseed.show',
      'https://arabseed.net',
  ]
  for d in domains:
    try:
      res = requests.get(d, headers=TMDB_HEADERS, timeout=4)
      if res.status_code == 200:
        return d
    except Exception:
      continue
  return 'https://arabseed.store'


AKWAM_BASE_DOMAIN = get_active_akwam_domain()
ARABSEED_BASE_DOMAIN = get_active_arabseed_domain()


def get_akwam_headers(referer_url=None):
  ref = safe_url(referer_url) if referer_url else f'{AKWAM_BASE_DOMAIN}/'
  return {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
      'Referer': ref,
  }


# ==============================================================================
# 2. دوال معالجة صور TMDB
# ==============================================================================


def format_poster(poster_path):
  return f'https://image.tmdb.org/t/p/w780{poster_path}' if poster_path else ''


def format_backdrop(backdrop_path):
  return (
      f'https://image.tmdb.org/t/p/w1280{backdrop_path}' if backdrop_path else ''
  )


# ==============================================================================
# 3. محرك كشط تقشير بطاقات أكوام (Akwam Cards)
# ==============================================================================


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
# 4. دوال اقتناص روابط MP4 الاحتياطية (المزودات)
# ==============================================================================


# 🔹 أ) المزود الأول: أكوام (Akwam Provider)
def fetch_akwam_stream(title, orig_title, media_type):
  search_queries = [q for q in [title, orig_title] if q]
  card = None

  for q in search_queries:
    search_url = safe_url(f'{AKWAM_BASE_DOMAIN}/search?q={q}')
    res = requests.get(search_url, headers=get_akwam_headers(), timeout=6)
    soup = BeautifulSoup(res.text, 'html.parser')
    selector = (
        'a[href*="/movie/"]' if media_type == 'movie' else 'a[href*="/series/"]'
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
    s_res = requests.get(
        safe_url(item_url), headers=get_akwam_headers(item_url), timeout=6
    )
    soup_s = BeautifulSoup(s_res.text, 'html.parser')
    ep_card = soup_s.select_one('a[href*="/episode/"]')
    if ep_card and ep_card.get('href'):
      target_url = ep_card['href']
      if not target_url.startswith('http'):
        target_url = f"{AKWAM_BASE_DOMAIN}/{target_url.lstrip('/')}"

  res_t = requests.get(
      safe_url(target_url), headers=get_akwam_headers(target_url), timeout=6
  )
  soup_t = BeautifulSoup(res_t.text, 'html.parser')
  watch_btn = soup_t.select_one('a[href*="/watch/"], a.link-btn')
  if not watch_btn or not watch_btn.get('href'):
    return None

  watch_url = watch_btn['href']
  if not watch_url.startswith('http'):
    watch_url = f"{AKWAM_BASE_DOMAIN}/{watch_url.lstrip('/')}"

  res_w = requests.get(
      safe_url(watch_url), headers=get_akwam_headers(watch_url), timeout=6
  )
  raw_links = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4)[^\s"\'<>]*', res_w.text)

  qualities = []
  for idx, u in enumerate(list(set(raw_links))):
    if '#Intent;' in u:
      continue
    q_label = (
        '1080p FHD'
        if '1080' in u
        else (
            '720p HD'
            if '720' in u
            else ('480p SD' if '480' in u else f'أكوام {idx+1}')
        )
    )
    qualities.append({'quality': q_label, 'url': u, 'is_default': idx == 0})

  return qualities if qualities else None


# 🔹 ب) المزود الثاني الاحتياطي: عرب سيد (Arabseed Provider)
def fetch_arabseed_stream(title, orig_title):
  search_queries = [q for q in [title, orig_title] if q]
  forbidden = [
      '/main',
      '/recently',
      '/trend',
      '/orders',
      '/privacy-policy',
      '/dmca',
      '/movies',
      '/series',
  ]
  target_link = None

  for q in search_queries:
    try:
      s_url = f'{ARABSEED_BASE_DOMAIN}/find/?find={quote(q)}'
      res = requests.get(s_url, headers=TMDB_HEADERS, timeout=6)
      soup = BeautifulSoup(res.text, 'html.parser')

      for a in soup.find_all('a', href=True):
        href = a['href']
        if not href.startswith('http'):
          href = f"{ARABSEED_BASE_DOMAIN}/{href.lstrip('/')}"

        if not any(f in href.lower() for f in forbidden) and href != f'{ARABSEED_BASE_DOMAIN}/':
          if '%' in href or '/film/' in href or '/movie/' in href:
            target_link = href
            break
      if target_link:
        break
    except Exception:
      continue

  if not target_link:
    return None

  try:
    clean_base = target_link.rstrip('/')
    if clean_base.endswith('/watch'):
      clean_base = clean_base[:-6]
    dl_url = f'{clean_base}/download/'

    res_dl = requests.get(dl_url, headers=TMDB_HEADERS, timeout=6)
    raw_mp4 = re.findall(
        r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', res_dl.text
    )

    qualities = []
    for idx, u in enumerate(list(set(raw_mp4))):
      if '#Intent;' in u:
        continue
      q_label = (
          '1080p FHD'
          if '1080' in u
          else (
              '720p HD'
              if '720' in u
              else ('480p SD' if '480' in u else f'عرب سيد {idx+1}')
          )
      )
      qualities.append({'quality': q_label, 'url': u, 'is_default': idx == 0})

    return qualities if qualities else None
  except Exception:
    return None


# ==============================================================================
# 5. نقاط الـ API للتطبيق
# ==============================================================================


@app.route('/', methods=['GET'])
def index():
  return jsonify({
      'status': 'online',
      'engine': 'Hybrid Multi-Provider Scraping Engine (Akwam + Arabseed)',
      'akwam_domain': AKWAM_BASE_DOMAIN,
      'arabseed_domain': ARABSEED_BASE_DOMAIN,
      'version': '2.0.0',
  })


@app.route('/api/home', methods=['GET'])
def get_home():
  try:
    trending_movies, trending_tv = [], []
    try:
      m_url = f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA'
      t_url = (
          f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA'
      )

      m_res = requests.get(m_url, headers=TMDB_HEADERS, timeout=5)
      t_res = requests.get(t_url, headers=TMDB_HEADERS, timeout=5)

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
      print(f'⚠️ TMDB Error: {tmdb_err}')

    if not trending_movies:
      res_m = requests.get(
          f'{AKWAM_BASE_DOMAIN}/movies',
          headers=get_akwam_headers(),
          timeout=5,
      )
      trending_movies = parse_akwam_cards(
          BeautifulSoup(res_m.text, 'html.parser')
      )[:10]

    if not trending_tv:
      res_t = requests.get(
          f'{AKWAM_BASE_DOMAIN}/series',
          headers=get_akwam_headers(),
          timeout=5,
      )
      trending_tv = parse_akwam_cards(BeautifulSoup(res_t.text, 'html.parser'))[
          :10
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


@app.route('/api/stream', methods=['GET'])
def get_direct_stream():
  title = request.args.get('title', '')
  orig_title = request.args.get('original_title', '')
  media_type = request.args.get('type', 'movie').lower()

  if not title and not orig_title:
    return jsonify({'status': 'error', 'message': 'Title missing'}), 400

  # 1. المحاولة الأولى: كشط موقع أكوام
  streams = fetch_akwam_stream(title, orig_title, media_type)

  # 2. المحاولة الثانية التلقائية: كشط موقع عرب سيد إذا فشل أكوام
  if not streams:
    print(f"🔄 انتقال تلقائي إلى عرب سيد للفيلم: {title or orig_title}")
    streams = fetch_arabseed_stream(title, orig_title)

  if streams:
    return jsonify({
        'status': 'success',
        'data': {'title': title, 'type': media_type, 'streams': streams},
    })

  return (
      jsonify({
          'status': 'error',
          'message': 'Content not found in any available engine',
      }),
      404,
  )


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)

