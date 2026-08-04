import json
import re
from urllib.parse import quote, unquote, urljoin, urlparse
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, request
import requests

# ==============================================================================
# إعدادات التطبيق والسيرفر الرئيسي (Vercel Serverless Entrypoint)
# ==============================================================================

app = Flask(__name__)

# مفتاح TMDB الخاص بك والمُفعل
TMDB_API_KEY = "65687d1e167bc35f38ee0c88c3a37b74"
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# الهيدرز القياسية لطلبات الشبكة لمنع الحظر
TMDB_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}


# ==============================================================================
# 1. الدوال المساعدة والأمان للروابط والدومينات وتفكيك التشفير
# ==============================================================================

DIGITS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def base_encode(num, base):
  """تحويل الأرقام إلى قواعد نصية لفك تشفير Dean Edwards."""
  if num == 0:
    return DIGITS[0]
  res = []
  while num > 0:
    res.append(DIGITS[num % base])
    num //= base
  return ''.join(reversed(res))


def unpack_dean_edwards(script_text):
  """فك تشفير أكواد eval(function(p,a,c,k,e,d)...) لسيرفرات okhd و Vidmoly."""
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
  """تحويل وتشفير الروابط التي تحتوي على حروف عربية إلى ترميز ASCII آمن

  لتفادي أخطاء latin-1 أو HTTP 500 في سيرفرات Flask.
  """
  if not url:
    return url
  return quote(url, safe=':/?&=#%')


def get_active_akwam_domain():
  """الاكتشاف الديناميكي لنطاق موقع أكوام النشط حالياً

  عبر التوجيه التلقائي من ak.sv لمنع توقف التطبيق عند تغير الدومين.
  """
  try:
    res = requests.get(
        'https://ak.sv/',
        headers=TMDB_HEADERS,
        timeout=6,
        allow_redirects=True,
    )
    parsed = urlparse(res.url)
    active_domain = f'{parsed.scheme}://{parsed.netloc}'
    return active_domain
  except Exception as e:
    print(f'⚠️ Error resolving Akwam active domain: {e}')
    return 'https://akwam.it'


# تحديد النطاق النشط عند بدء التشغيل
AKWAM_BASE_DOMAIN = get_active_akwam_domain()


def get_akwam_headers(referer_url=None):
  """توليد الهيدرز المطلوبة لكشط موقع أكوام مع ضبط الـ Referer المناسب."""
  ref = safe_url(referer_url) if referer_url else f'{AKWAM_BASE_DOMAIN}/'
  return {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
      'Referer': ref,
  }


# ==============================================================================
# 2. دوال معالجة وتنسيق صور TMDB (HD Posters & Backdrops)
# ==============================================================================


def format_poster(poster_path):
  """معالجة وتكبير بوستر الفيلم العمودي ليكون عالي الدقة (w780)."""
  if not poster_path:
    return ''
  return f'https://image.tmdb.org/t/p/w780{poster_path}'


def format_backdrop(backdrop_path):
  """معالجة وتكبير غلاف الفيلم الأفقي ليكون عالي الدقة للسلايدر (w1280)."""
  if not backdrop_path:
    return ''
  return f'https://image.tmdb.org/t/p/w1280{backdrop_path}'


# ==============================================================================
# 3. محرك تقشير وتفكيك بطاقات أفلام ومسلسلات أكوام (Akwam Parser)
# ==============================================================================


def parse_akwam_cards(soup):
  """استخراج بيانات بطاقات المحتوى من صفحة HTML الخاصة بموقع أكوام."""
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

    # تجهيز كائن البيانات الموحد لضمان عدم انهيار أندرويد
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
# 4. مسارات ونقاط الـ API الكلية للتطبيق (Flask Routes)
# ==============================================================================


# 🟢 أ) فحص الحالة العامة وفحص النطاق
@app.route('/', methods=['GET'])
def index():
  return jsonify({
      'status': 'online',
      'engine': 'Akwam + Local HLS Proxy Engine',
      'active_domain': AKWAM_BASE_DOMAIN,
      'version': '2.0.0',
  })


# 🚀 ب) مسار خادم البروكسي المحلي لتمرير الترويسات ومنع حظر HTTP 403 في ExoPlayer
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
        target_url, headers=headers_dict, stream=True, timeout=12
    )
    content_type = resp.headers.get('Content-Type', '')

    # 1. إذا كان الملف المطلوب هو قائمة التشغيل (.m3u8)
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
      # 2. إذا كان المطلوب هو قطعة فيديو ثنائية (.ts)

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


# 🌐 ج) الشاشة الرئيسية الهجينة (TMDB + Fallback Akwam)
@app.route('/api/home', methods=['GET'])
def get_home():
  try:
    trending_movies = []
    trending_tv = []

    # 1. محاولة الجلب من TMDB
    try:
      movies_url = f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA'
      tv_url = (
          f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA'
      )

      m_res = requests.get(movies_url, headers=TMDB_HEADERS, timeout=6)
      t_res = requests.get(tv_url, headers=TMDB_HEADERS, timeout=6)

      if m_res.status_code == 200:
        m_json = m_res.json()
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
            for m in m_json.get('results', [])[:10]
            if m.get('poster_path')
        ]

      if t_res.status_code == 200:
        t_json = t_res.json()
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
            for t in t_json.get('results', [])[:10]
            if t.get('poster_path')
        ]
    except Exception as tmdb_err:
      print(f'⚠️ TMDB Fetch Exception: {tmdb_err}')

    # 2. التراجع إلى أكوام في حال عدم توفر البيانات من TMDB
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


# 📂 د) نقطة الكتالوج الشاملة (لزر "عرض الكل" والترقيم والفلترة)
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


# 🔍 هـ) البحث المباشر في TMDB
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


# 🌀 و) تفاصيل المسلسل (المواسم والحلقات من أكوام)
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


# 🎬 ز) اقتناص روابط البث المباشرة (.mp4 من أكوام OR سيرفرات HLS المشفرة عبر البروكسي)
@app.route('/api/stream', methods=['GET'])
def get_direct_stream():
  embed_url = request.args.get('embed_url', '')
  title = request.args.get('title', '')
  orig_title = request.args.get('original_title', '')
  media_type = request.args.get('type', 'movie').lower()

  # 1. إذا تم تمرير رابط سيرفر مشغل مضمن (مثل okhd.site أو Vidmoly)
  if embed_url:
    try:
      emb_headers = {
          'User-Agent': TMDB_HEADERS['User-Agent'],
          'Referer': 'https://larroza.mom/',
      }
      res_emb = requests.get(embed_url, headers=emb_headers, timeout=8)

      # فك تشفير Dean Edwards تلقائياً
      unpacked_code = unpack_dean_edwards(res_emb.text)

      m3u8_links = re.findall(
          r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked_code
      )
      if m3u8_links:
        raw_stream = m3u8_links[0]
        h_json = json.dumps(
            {'User-Agent': TMDB_HEADERS['User-Agent'], 'Referer': embed_url}
        )

        # تحويل الرابط إلى رابط بروكسي محلي شغال 100%
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

  # 2. في حالة عدم وجود embed_url، يتم تنفيذ كشط موقع أكوام الأصلي بالكامل
  if not title and not orig_title:
    return jsonify({'status': 'error', 'message': 'Title missing'}), 400

  # قائمة المصطلحات للبحث بها لمنع خطأ 404
  search_queries = [q for q in [title, orig_title] if q]

  try:
    card = None
    for q in search_queries:
      search_url = safe_url(f'{AKWAM_BASE_DOMAIN}/search?q={q}')
      search_res = requests.get(
          search_url, headers=get_akwam_headers(), timeout=8
      )
      soup = BeautifulSoup(search_res.text, 'html.parser')

      selector = (
          'a[href*="/movie/"]'
          if media_type == 'movie'
          else 'a[href*="/series/"]'
      )
      card = soup.select_one(selector)
      if card and card.get('href'):
        break  # تم العثور على العنصر في أكوام بنجاح

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

    # استخراج روابط mp4 عبر النماذج التعبيرية (Regex)
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


# ==============================================================================
# نقطة تشغيل السيرفر المحلية (Development / Local Testing)
# ==============================================================================

if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)

