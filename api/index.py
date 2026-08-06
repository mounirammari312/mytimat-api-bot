from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import requests
import re

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
# 1. اكتشاف دومين أكوام النشط تلقائياً (فقط إذا كان مفعلاً في القائمة)
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
# 2. قائمة المزودات المركزية (التحكم الكلي بما يتم كشطه وتفعيله)
# ==============================================================================

def get_providers_config():
    return [
                    {
                'name': 'qfilm',
                'domain': 'https://a.qfilm.tv',
                'search_path': '/?s={query}',
                'card_selector': (
                    'a[href*="/watch/"], a[href*="/play.php"], a[href*="vid="'
                    ')'
                ),
                'watch_selector': (
                    'iframe, [data-link], [data-url], [data-post],'
                    ' a[href*="watch.php"], a[href*="play.php"]'
                ),
                'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
                'requires_unpack': True,
                'ajax_required': False,
            },

    ]


# ==============================================================================
# 3. دوال تنسيق بطاقات أكوام و TMDB
# ==============================================================================

def format_poster(poster_path):
    return f'https://image.tmdb.org/t/p/w780{poster_path}' if poster_path else ''

def format_backdrop(backdrop_path):
    return f'https://image.tmdb.org/t/p/w1280{backdrop_path}' if backdrop_path else ''

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

        title_el = card.select_one('h3.entry-title, .entry-title, h3, a.entry-title')
        img_el = card.select_one('img')

        title = 'غير متوفر'
        if title_el and title_el.get_text(strip=True):
            title = title_el.get_text(strip=True)
        elif img_el and img_el.get('alt'):
            title = img_el['alt']

        poster_url = ''
        if img_el:
            poster_url = img_el.get('data-src') or img_el.get('data-lazy') or img_el.get('src')
            if poster_url and 'placeholder.png' in poster_url:
                poster_url = img_el.get('data-src') or poster_url

        badge_els = card.select('span.badge, div.badge, span.quality')
        badges = [b.get_text(strip=True) for b in badge_els if b.get_text(strip=True)]
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
# 4. مسارات الـ API الكلية والكاملة (All Required Routes)
# ==============================================================================

@app.route('/', methods=['GET'])
def index():
    active_providers = [p['name'] for p in get_providers_config()]
    return jsonify({
        'status': 'online',
        'mode': 'Strict Dynamic Providers Engine',
        'active_providers': active_providers,
        'version': '6.4.0',
    })

@app.route('/api/config', methods=['GET'])
def get_config():
    """تزويد التطبيق حصرياً بالمواقع الموجودة في قائمة المزودات النشطة."""
    return jsonify({
        'status': 'success',
        'version': '6.4.0',
        'providers': get_providers_config(),
    })

@app.route('/api/home', methods=['GET'])
def get_home():
    """جلب القوائم الرئيسية للأفلام والمسلسلات عبر TMDB"""
    try:
        trending_movies = []
        trending_tv = []

        try:
            movies_url = f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA'
            tv_url = f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA'

            m_res = requests.get(movies_url, headers=TMDB_HEADERS, timeout=4)
            t_res = requests.get(tv_url, headers=TMDB_HEADERS, timeout=4)

            providers = get_providers_config()
            provider_names = [p['name'] for p in providers]

            if m_res.status_code == 200:
                trending_movies = [
                    {
                        'id': str(m.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(m.get('title') or m.get('original_title', ''))}" if 'akwam' in provider_names else '',
                        'title': m.get('title') or m.get('original_title', ''),
                        'original_title': m.get('original_title', ''),
                        'poster': format_poster(m.get('poster_path')),
                        'backdrop': format_backdrop(m.get('backdrop_path') or m.get('poster_path')),
                        'rating': round(m.get('vote_average', 0), 1),
                        'tags': ['TMDB', str(m.get('release_date', '')[:4]) if m.get('release_date') else '2026'],
                        'type': 'movie',
                    }
                    for m in m_res.json().get('results', [])[:10]
                    if m.get('poster_path')
                ]

            if t_res.status_code == 200:
                trending_tv = [
                    {
                        'id': str(t.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(t.get('name') or t.get('original_name', ''))}" if 'akwam' in provider_names else '',
                        'title': t.get('name') or t.get('original_name', ''),
                        'original_title': t.get('original_name', ''),
                        'poster': format_poster(t.get('poster_path')),
                        'backdrop': format_backdrop(t.get('backdrop_path') or t.get('poster_path')),
                        'rating': round(t.get('vote_average', 0), 1),
                        'tags': ['TMDB', str(t.get('first_air_date', '')[:4]) if t.get('first_air_date') else '2026'],
                        'type': 'tv',
                    }
                    for t in t_res.json().get('results', [])[:10]
                    if t.get('poster_path')
                ]
        except Exception as tmdb_err:
            print(f'⚠️ TMDB Fetch Exception: {tmdb_err}')

        provider_names = [p['name'] for p in get_providers_config()]
        if not trending_movies and 'akwam' in provider_names:
            try:
                res_m = requests.get(f'{AKWAM_BASE_DOMAIN}/movies', headers=get_akwam_headers(), timeout=4)
                soup_m = BeautifulSoup(res_m.text, 'html.parser')
                trending_movies = parse_akwam_cards(soup_m)[:10]
            except Exception:
                pass

        if not trending_tv and 'akwam' in provider_names:
            try:
                res_t = requests.get(f'{AKWAM_BASE_DOMAIN}/series', headers=get_akwam_headers(), timeout=4)
                soup_t = BeautifulSoup(res_t.text, 'html.parser')
                trending_tv = parse_akwam_cards(soup_t)[:10]
            except Exception:
                pass

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
    """جلب قائمة الكتالوج (مرتبط بأكوام حصرياً إذا كان مفعلاً)"""
    provider_names = [p['name'] for p in get_providers_config()]
    if 'akwam' not in provider_names:
        return jsonify({'status': 'success', 'data': {'items': []}})

    cat_type = request.args.get('type', 'movies').lower()
    page = request.args.get('page', '1')
    catalog_url = safe_url(f'{AKWAM_BASE_DOMAIN}/{cat_type}?page={page}')

    try:
        res = requests.get(catalog_url, headers=get_akwam_headers(catalog_url), timeout=4)
        soup = BeautifulSoup(res.text, 'html.parser')
        items = parse_akwam_cards(soup)
        return jsonify({
            'status': 'success',
            'data': {
                'type': cat_type,
                'current_page': int(page),
                'total_pages': 10,
                'has_next_page': True,
                'items_count': len(items),
                'items': items,
            },
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/search', methods=['GET'])
def search():
    """البحث الديناميكي: توليد الروابط حصرياً بناءً على قائمة المزودات النشطة الحالية"""
    query = request.args.get('q', '')
    if not query:
        return jsonify({'status': 'error', 'message': 'Query missing'}), 400

    try:
        search_url = f'{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={quote(query)}&language=ar-SA'
        res = requests.get(search_url, headers=TMDB_HEADERS, timeout=8)

        if res.status_code != 200:
            return jsonify({'status': 'success', 'data': []})

        res_json = res.json()
        items = []
        providers = get_providers_config()

        for item in res_json.get('results', []):
            m_type = item.get('media_type')
            if m_type in ['movie', 'tv']:
                vote_avg = item.get('vote_average')
                rating = round(vote_avg, 1) if isinstance(vote_avg, (int, float)) else 0.0

                title = item.get('title') or item.get('name') or item.get('original_title') or 'بدون عنوان'
                orig_title = item.get('original_name') or item.get('original_title') or ''
                poster_path = item.get('poster_path')

                sources = {}
                for p in providers:
                    p_name = p['name']
                    p_domain = (
                        AKWAM_BASE_DOMAIN if p_name == 'akwam' 
                        else LARROZA_BASE_DOMAIN if p_name == 'larroza' 
                        else p['domain']
                    )
                    search_path = p['search_path'].format(query=quote(title))
                    sources[p_name] = f"{p_domain}{search_path}"

                default_url = sources.get(list(sources.keys())[0], '') if sources else ''

                items.append({
                    'id': str(item.get('id', '')),
                    'url': default_url,
                    'sources': sources,
                    'title': title,
                    'original_title': orig_title,
                    'poster': format_poster(poster_path),
                    'backdrop': format_backdrop(item.get('backdrop_path') or poster_path),
                    'rating': rating,
                    'tags': ['TMDB'],
                    'type': m_type,
                })

        return jsonify({'status': 'success', 'data': items})

    except Exception as e:
        print(f"⚠️ Search Error: {e}")
        return jsonify({'status': 'success', 'data': []})


@app.route('/api/series-details', methods=['GET'])
def get_series_details():
    """جلب تفاصيل وحلقات المسلسل (يعتمد على أكوام إذا كان مفعلاً، أو TMDB)"""
    series_url = request.args.get('url', '').strip()
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()
    orig_title = request.args.get('original_title', '').strip()
    selected_season = request.args.get('season', '1').strip()

    provider_names = [p['name'] for p in get_providers_config()]
    clean_tmdb_id = tmdb_id if (tmdb_id and tmdb_id.isdigit()) else None

    if 'akwam' in provider_names and series_url and series_url.startswith('http') and '/series/' in series_url:
        try:
            target_url = safe_url(series_url)
            res = requests.get(target_url, headers=get_akwam_headers(target_url), timeout=4)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                episode_cards = soup.select('a[href*="/episode/"]')
                episodes = [{'title': ep.get_text(strip=True), 'url': ep['href'] if ep['href'].startswith('http') else f"{AKWAM_BASE_DOMAIN}/{ep['href'].lstrip('/')}"} for ep in episode_cards]
                if episodes:
                    return jsonify({'status': 'success', 'data': {'seasons': [], 'episodes': episodes}})
        except Exception:
            pass

    if clean_tmdb_id:
        try:
            season_num = int(selected_season) if selected_season.isdigit() else 1
            ep_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}&language=ar-SA'
            res_ep = requests.get(ep_url, headers=TMDB_HEADERS, timeout=4).json()

            episodes = []
            for ep in res_ep.get('episodes', []):
                ep_num = ep.get('episode_number')
                episodes.append({
                    'episode_number': ep_num,
                    'title': f"الحلقة {ep_num} - {ep.get('name', '')}",
                    'search_title': f"{title} الموسم {season_num} الحلقة {ep_num}" if title else f"الموسم {season_num} الحلقة {ep_num}",
                    'search_orig_title': f"{orig_title} S{season_num:02d}E{ep_num:02d}" if orig_title else f"S{season_num:02d}E{ep_num:02d}",
                })

            return jsonify({
                'status': 'success',
                'data': {'current_season': season_num, 'seasons': [], 'episodes': episodes},
            })
        except Exception:
            pass

    return jsonify({
        'status': 'success',
        'data': {'current_season': 1, 'seasons': [], 'episodes': []},
        'message': 'لم يتم العثور على حلقات',
    })


@app.route('/api/movie-details', methods=['GET'])
def get_movie_details():
    """جلب تفاصيل الفيلم من TMDB"""
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()
    clean_id = tmdb_id if (tmdb_id and tmdb_id.isdigit()) else None

    if not clean_id and title:
        try:
            search_url = f'{TMDB_BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={quote(title)}&language=ar-SA'
            res = requests.get(search_url, headers=TMDB_HEADERS, timeout=4)
            if res.status_code == 200:
                results = res.json().get('results', [])
                if results:
                    clean_id = str(results[0].get('id', ''))
        except Exception:
            pass

    if not clean_id:
        return jsonify({'status': 'success', 'data': None})

    try:
        detail_url = f'{TMDB_BASE_URL}/movie/{clean_id}?api_key={TMDB_API_KEY}&language=ar-SA'
        data = requests.get(detail_url, headers=TMDB_HEADERS, timeout=5).json()
        return jsonify({
            'status': 'success',
            'data': {
                'id': str(data.get('id', '')),
                'title': data.get('title', ''),
                'original_title': data.get('original_title', ''),
                'overview': data.get('overview', ''),
                'release_date': data.get('release_date', ''),
                'poster': format_poster(data.get('poster_path')),
                'backdrop': format_backdrop(data.get('backdrop_path')),
            },
        })
    except Exception:
        return jsonify({'status': 'success', 'data': None})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

