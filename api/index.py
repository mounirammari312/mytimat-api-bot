from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import requests
import json

app = Flask(__name__)

TMDB_API_KEY = '65687d1e167bc35f38ee0c88c3a37b74'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

UPSTASH_REDIS_REST_URL = "https://immortal-redfish-188577.upstash.io"
UPSTASH_REDIS_REST_TOKEN = "gQAAAAAAAuChAAIgcDI2MGIzYmQwZTdhYTQ0Y2MxYjFmZTU1YjU2ZGMyNGI0Mw"
CACHE_TTL_SECONDS = 6 * 3600


def get_cached(key):
    if not UPSTASH_REDIS_REST_URL or "YOUR-DATABASE" in UPSTASH_REDIS_REST_URL:
        return None
    try:
        headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
        res = requests.post(UPSTASH_REDIS_REST_URL, json=["GET", key], headers=headers, timeout=3)
        if res.status_code == 200:
            raw_data = res.json().get("result")
            if raw_data:
                return json.loads(raw_data)
    except Exception as e:
        print(f"⚠️ Upstash Redis GET Error: {e}")
    return None


def set_cached(key, data, ttl=CACHE_TTL_SECONDS):
    if not UPSTASH_REDIS_REST_URL or "YOUR-DATABASE" in UPSTASH_REDIS_REST_URL:
        return
    try:
        headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
        requests.post(UPSTASH_REDIS_REST_URL, json=["SET", key, json.dumps(data), "EX", ttl], headers=headers, timeout=3)
    except Exception as e:
        print(f"⚠️ Upstash Redis SET Error: {e}")


TMDB_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}

LARROZA_BASE_DOMAIN = 'https://larroza.mom'


def safe_url(url):
    return quote(url, safe=':/?&=#%') if url else url


def get_active_akwam_domain():
    try:
        res = requests.get('https://ak.sv/', headers=TMDB_HEADERS, timeout=3, allow_redirects=True)
        parsed = urlparse(res.url)
        return f'{parsed.scheme}://{parsed.netloc}'
    except Exception:
        return 'https://akwam.site'


AKWAM_BASE_DOMAIN = get_active_akwam_domain()


def get_akwam_headers(referer_url=None):
    ref = safe_url(referer_url) if referer_url else f'{AKWAM_BASE_DOMAIN}/'
    return {'User-Agent': TMDB_HEADERS['User-Agent'], 'Referer': ref}


def format_poster(poster_path):
    return f'https://image.tmdb.org/t/p/w780{poster_path}' if poster_path else ''


def format_backdrop(backdrop_path):
    return f'https://image.tmdb.org/t/p/w1280{backdrop_path}' if backdrop_path else ''


def parse_akwam_cards(soup):
    card_containers = soup.select('div.widget-body div.col-lg-2, div.widget-body div.col-md-3, div.entry-box')
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
        title = title_el.get_text(strip=True) if title_el and title_el.get_text(strip=True) else (img_el.get('alt') if img_el else 'غير متوفر')

        poster_url = ''
        if img_el:
            poster_url = img_el.get('data-src') or img_el.get('data-lazy') or img_el.get('src') or ''

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


@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'status': 'online',
        'mode': 'JSON Rules Engine + QuickJS Micro-Scripts + Upstash Redis Cache',
        'active_domains': {
            'akwam': AKWAM_BASE_DOMAIN,
            'larroza': LARROZA_BASE_DOMAIN,
        },
        'version': '9.10.0-Production',
    })


@app.route('/api/config', methods=['GET'])
def get_config():
    """إرسال قواعد المزودات لتطبيق الأندرويد ليتولى كشطها محلياً"""
    return jsonify({
        'status': 'success',
        'version': '9.10.0-Production',
        'providers': [
            {
                'name': 'netplayz',
                'domain': 'https://netplayz.icu',
                'search_path': '/watch?type=movie&id={tmdb_id}',
                'card_selector': '',
                'movie_selector': '',
                'series_selector': '',
                'watch_selector': '',
                'iframe_selector': 'iframe',
                'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
                'tmdb_mode': True,
                'requires_unpack': True,
                'ajax_required': True,
                'extractor_script': r"""
                    (function() {
                        var directMatch = __HTML__.match(/https?:\/\/[^\s"'<>]+\.(?:m3u8|mp4)[^\s"'<>]*/i);
                        if (directMatch) {
                            return { url: directMatch[0], referer: __PAGE_URL__, quality: '1080p Clean' };
                        }
                        var fileMatch = __HTML__.match(/(?:file|source|src)\s*:\s*["']([^"']+\.(?:m3u8|mp4)[^"']*)["']/i);
                        if (fileMatch) {
                            return { url: fileMatch[1], referer: __PAGE_URL__, quality: '1080p Clean' };
                        }
                        var iframeSrc = __HTML__.match(/<iframe[^>]+src=["']([^"']+)["']/i);
                        if (iframeSrc && iframeSrc[1].startsWith('http')) {
                            return { url: iframeSrc[1], referer: __PAGE_URL__, quality: 'Embed' };
                        }
                        return null;
                    })();
                """
            }
        ],
    })


def fetch_tmdb_discover(endpoint_path, query_params, media_type, default_tag='TMDB', limit=10):
    url = f"{TMDB_BASE_URL}/{endpoint_path}?api_key={TMDB_API_KEY}&language=ar-SA&{query_params}"
    try:
        res = requests.get(url, headers=TMDB_HEADERS, timeout=2.5)
        if res.status_code == 200:
            items = []
            for item in res.json().get('results', [])[:limit]:
                if not item.get('poster_path'):
                    continue
                title = item.get('title') or item.get('name') or item.get('original_title') or item.get('original_name', '')
                orig_title = item.get('original_title') or item.get('original_name', '')
                release_date = item.get('release_date') or item.get('first_air_date', '')
                year = str(release_date)[:4] if release_date else ''
                search_query = quote(orig_title if orig_title else title)

                items.append({
                    'id': str(item.get('id', '')),
                    'url': f"{AKWAM_BASE_DOMAIN}/search?q={search_query}",
                    'title': title,
                    'original_title': orig_title,
                    'poster': format_poster(item.get('poster_path')),
                    'backdrop': format_backdrop(item.get('backdrop_path') or item.get('poster_path')),
                    'rating': round(item.get('vote_average', 0), 1),
                    'tags': [default_tag, year] if year else [default_tag],
                    'type': media_type,
                })
            return items
    except Exception as e:
        print(f"⚠️ TMDB Discover Error: {e}")
    return []


@app.route('/api/home', methods=['GET'])
def get_home():
    CACHE_KEY = 'home_data_v7_rich_ui'
    cached = get_cached(CACHE_KEY)
    if cached is not None:
        return jsonify(cached)

    try:
        sections_list = [
            {'key': 'trending_movies', 'title': '🔥 الأفلام الأكثر شهرة', 'has_see_all': True, 'see_all_params': {'type': 'movies', 'page': 1}, 'items': fetch_tmdb_discover('trending/movie/week', '', 'movie', '🔥 رائج')},
            {'key': 'trending_tv', 'title': '📺 المسلسلات الأكثر مشاهدة', 'has_see_all': True, 'see_all_params': {'type': 'series', 'page': 1}, 'items': fetch_tmdb_discover('trending/tv/week', '', 'tv', '📺 مسلسلات')},
            {'key': 'action_movies', 'title': '💥 أفلام الحركة والإثارة', 'has_see_all': False, 'see_all_params': {}, 'items': fetch_tmdb_discover('discover/movie', 'with_genres=28&sort_by=popularity.desc&vote_count.gte=100', 'movie', '💥 أكشن')},
            {'key': 'animation_movies', 'title': '🎨 روائع الأنمي والكرتون', 'has_see_all': False, 'see_all_params': {}, 'items': fetch_tmdb_discover('discover/movie', 'with_genres=16,10751&sort_by=popularity.desc&vote_count.gte=50', 'movie', '🎨 أنمي')},
            {'key': 'korean_drama', 'title': '🇰🇷 الدراما والمسلسلات الكورية', 'has_see_all': False, 'see_all_params': {}, 'items': fetch_tmdb_discover('discover/tv', 'with_original_language=ko&sort_by=popularity.desc&vote_count.gte=20', 'tv', '🇰🇷 كوري')},
            {'key': 'top_rated_movies', 'title': '⭐ سينما النخبة (الأعلى تقييماً)', 'has_see_all': False, 'see_all_params': {}, 'items': fetch_tmdb_discover('movie/top_rated', 'vote_count.gte=500', 'movie', '⭐ الأعلى تقييماً')},
        ]
        result = {'status': 'success', 'data': sections_list}
        set_cached(CACHE_KEY, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/series-details', methods=['GET'])
def get_series_details():
    series_url = request.args.get('url', '').strip()
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()
    orig_title = request.args.get('original_title', '').strip()
    selected_season = request.args.get('season', '1').strip()

    cache_key = f'series:{tmdb_id or series_url}:{selected_season}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    clean_tmdb_id = tmdb_id if tmdb_id.isdigit() else (series_url if series_url.isdigit() else None)

    if clean_tmdb_id:
        try:
            tmdb_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}?api_key={TMDB_API_KEY}&language=ar-SA'
            res_tv = requests.get(tmdb_url, headers=TMDB_HEADERS, timeout=4).json()
            seasons = [
                {'season_number': s.get('season_number', 0), 'title': s.get('name') or f"الموسم {s.get('season_number')}", 'episode_count': s.get('episode_count', 0)}
                for s in res_tv.get('seasons', []) if s.get('season_number', 0) > 0
            ]
            season_num = int(selected_season) if selected_season.isdigit() else 1
            ep_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}&language=ar-SA'
            res_ep = requests.get(ep_url, headers=TMDB_HEADERS, timeout=4).json()

            episodes = [
                {
                    'episode_number': ep.get('episode_number'),
                    'title': f"الحلقة {ep.get('episode_number')} - {ep.get('name', '')}",
                    'search_title': f'{title} الموسم {season_num} الحلقة {ep.get("episode_number")}' if title else f'الموسم {season_num} الحلقة {ep.get("episode_number")}',
                    'search_orig_title': f'{orig_title} S{season_num:02d}E{ep.get("episode_number"):02d}' if orig_title else f'S{season_num:02d}E{ep.get("episode_number"):02d}',
                }
                for ep in res_ep.get('episodes', [])
            ]
            res_data = {'status': 'success', 'data': {'current_season': season_num, 'seasons': seasons, 'episodes': episodes}}
            set_cached(cache_key, res_data)
            return jsonify(res_data)
        except Exception as tmdb_err:
            print(f'⚠️ TMDB Series Error: {tmdb_err}')

    return jsonify({'status': 'success', 'data': {'current_season': 1, 'seasons': [], 'episodes': []}})


@app.route('/api/movie-details', methods=['GET'])
def get_movie_details():
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()

    cache_key = f'movie:{tmdb_id or title}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    clean_id = tmdb_id if tmdb_id.isdigit() else None
    if not clean_id and title:
        try:
            search_url = f'{TMDB_BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={quote(title)}&language=ar-SA'
            res = requests.get(search_url, headers=TMDB_HEADERS, timeout=4).json()
            if res.get('results'):
                clean_id = str(res['results'][0].get('id', ''))
        except Exception:
            pass

    if not clean_id:
        return jsonify({'status': 'success', 'data': None})

    try:
        detail_url = f'{TMDB_BASE_URL}/movie/{clean_id}?api_key={TMDB_API_KEY}&language=ar-SA&append_to_response=credits,videos'
        res = requests.get(detail_url, headers=TMDB_HEADERS, timeout=4).json()
        result = {
            'status': 'success',
            'data': {
                'id': str(res.get('id', '')),
                'title': res.get('title', ''),
                'original_title': res.get('original_title', ''),
                'overview': res.get('overview', ''),
                'release_date': res.get('release_date', ''),
                'runtime': res.get('runtime', 0),
                'rating': round(res.get('vote_average', 0), 1),
                'poster': format_poster(res.get('poster_path')),
                'backdrop': format_backdrop(res.get('backdrop_path')),
                'genres': [g.get('name', '') for g in res.get('genres', [])],
                'cast': [{'name': c.get('name', ''), 'character': c.get('character', '')} for c in res.get('credits', {}).get('cast', [])[:10]],
                'videos': [{'key': v.get('key', ''), 'name': v.get('name', ''), 'site': v.get('site', ''), 'type': v.get('type', '')} for v in res.get('videos', {}).get('results', [])[:5]],
            },
        }
        set_cached(cache_key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

