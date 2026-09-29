

from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import requests
import json
import re

# استيراد محرك التخفي وانتحال بصمة TLS/JA3 مع Fallback لمكتبة requests
try:
    from curl_cffi import requests as stealth_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

# ==============================================================================
# 🛠️ إعدادات التطبيق والسيرفر الرئيسي (Vercel Entrypoint)
# ==============================================================================

app = Flask(__name__)

TMDB_API_KEY = '65687d1e167bc35f38ee0c88c3a37b74'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

# ==============================================================================
# ⚡ Upstash Redis Configuration
# ==============================================================================

UPSTASH_REDIS_REST_URL = "https://immortal-redfish-188577.upstash.io"
UPSTASH_REDIS_REST_TOKEN = "gQAAAAAAAuChAAIgcDI2MGIzYmQwZTdhYTQ0Y2MxYjFmZTU1YjU2ZGMyNGI0Mw"
CACHE_TTL_SECONDS = 6 * 3600  # 6 ساعات صلاحية الكاش


def get_cached(key):
    """استرجاع النتيجة من Upstash Redis عبر REST API."""
    if not UPSTASH_REDIS_REST_URL or "YOUR-DATABASE" in UPSTASH_REDIS_REST_URL:
        return None
    try:
        headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
        payload = ["GET", key]
        res = requests.post(UPSTASH_REDIS_REST_URL, json=payload, headers=headers, timeout=3)
        if res.status_code == 200:
            raw_data = res.json().get("result")
            if raw_data:
                return json.loads(raw_data)
    except Exception as e:
        print(f"⚠️ Upstash Redis GET Error: {e}")
    return None


def set_cached(key, data, ttl=CACHE_TTL_SECONDS):
    """حفظ النتيجة في Upstash Redis مع تحديد زمن الصلاحية TTL."""
    if not UPSTASH_REDIS_REST_URL or "YOUR-DATABASE" in UPSTASH_REDIS_REST_URL:
        return
    try:
        headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
        payload = ["SET", key, json.dumps(data), "EX", ttl]
        requests.post(UPSTASH_REDIS_REST_URL, json=payload, headers=headers, timeout=3)
    except Exception as e:
        print(f"⚠️ Upstash Redis SET Error: {e}")


TMDB_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

# v12.2.7: Larroza's old domain redirects through 9 hops to llaroza.click.
# Direct domain avoids the redirect chain.
LARROZA_BASE_DOMAIN = 'https://llaroza.click'


# ==============================================================================
# 🎯 محرك التدقيق والتطابق الصارم (Strict Matching Engine)
# ==============================================================================

def clean_query_term(text):
    """تنظيف استعلام البحث من الرموز الخاصة التي تعطل محركات بحث المواقع."""
    if not text:
        return ""
    cleaned = re.sub(r'[:\-_.,?!()\[\]/\\+*&^%$#@~`"\']', ' ', str(text))
    return ' '.join(cleaned.split()).strip()


# ==============================================================================
# 🥷 التقنية 2: محرك انتحال بصمة المتصفح (TLS / JA3 Spoofing)
# ==============================================================================

def stealth_fetch(url, referer=None):
    """طلب فائق التخفي يطابق بصمة Google Chrome 124 الثنائية لتجاوز جدران الحماية."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }
    if referer:
        headers["Referer"] = referer

    if HAS_CURL_CFFI:
        return stealth_requests.get(
            url,
            headers=headers,
            impersonate="chrome124",
            timeout=8,
            allow_redirects=True
        )
    return requests.get(url, headers=headers, timeout=8, allow_redirects=True)


# ==============================================================================
# 🏦 التقنية 4: مستودع الجلسات السحابي المشترك (Shared Session Vault)
# ==============================================================================

def get_vault_session(site_key, target_url):
    """استرجاع هوية جلسة صالحة ومفحوصة من Redis، أو تجديدها آلياً دون حظر."""
    cache_key = f"vault:session:{site_key}"
    cached_session = get_cached(cache_key)
    if cached_session:
        return cached_session

    try:
        res = stealth_fetch(target_url)
        if res.status_code in [200, 301, 302]:
            cookies_dict = res.cookies.get_dict() if hasattr(res.cookies, "get_dict") else dict(res.cookies)
            cookie_parts = [f"{k}={v}" for k, v in cookies_dict.items()]
            cookie_header = "; ".join(cookie_parts)

            vault_data = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Cookie": cookie_header,
                "Referer": f"{target_url.rstrip('/')}/"
            }

            set_cached(cache_key, vault_data, ttl=2 * 3600)
            return vault_data
    except Exception as e:
        print(f"⚠️ Vault Session Error for {site_key}: {e}")

    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"{target_url.rstrip('/')}/"
    }


# ==============================================================================
# 1. اكتشاف دومين أكوام ومساعدات التنسيق
# ==============================================================================

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
        return 'https://akwam.site'


AKWAM_BASE_DOMAIN = get_active_akwam_domain()


def format_poster(poster_path):
    return f'https://image.tmdb.org/t/p/w780{poster_path}' if poster_path else ''


def format_backdrop(backdrop_path):
    return f'https://image.tmdb.org/t/p/w1280{backdrop_path}' if backdrop_path else ''


def format_profile(profile_path):
    return f'https://image.tmdb.org/t/p/w185{profile_path}' if profile_path else ''


def resolve_tmdb_tv_id(candidate_id, title=None, orig_title=None):
    """استخراج أو البحث عن معرّف المسلسل الرقمي في TMDB بدقة عالية."""
    if candidate_id and str(candidate_id).strip().isdigit():
        return str(candidate_id).strip()

    search_queries = [orig_title, title]
    for q in search_queries:
        if not q:
            continue
        try:
            cleaned = clean_query_term(q)
            s_url = f'{TMDB_BASE_URL}/search/tv?api_key={TMDB_API_KEY}&query={quote(cleaned)}&language=ar-SA'
            s_res = requests.get(s_url, headers=TMDB_HEADERS, timeout=3.5)
            if s_res.status_code == 200:
                results = s_res.json().get('results', [])
                if results:
                    return str(results[0].get('id'))
        except Exception as e:
            print(f"⚠️ Search TMDB TV ID Error for '{q}': {e}")
    return None


def fetch_tmdb_series_meta(clean_tmdb_id):
    """جلب القصة والممثلين بالصور والمسلسلات المشابهة من TMDB."""
    if not clean_tmdb_id:
        return "", [], []

    try:
        t_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}?api_key={TMDB_API_KEY}&language=ar-SA&append_to_response=credits,similar'
        res = requests.get(t_url, headers=TMDB_HEADERS, timeout=3.5)
        if res.status_code != 200:
            return "", [], []

        data = res.json()
        overview = data.get('overview', '')
        cast = [
            {
                'name': c.get('name', ''),
                'character': c.get('character', ''),
                'profile': format_profile(c.get('profile_path')),
            }
            for c in data.get('credits', {}).get('cast', [])[:10]
        ]
        similar = [
            {
                'id': str(s.get('id', '')),
                'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(s.get('original_name') or s.get('name', '')))}",
                'title': s.get('name') or s.get('original_name', ''),
                'original_title': s.get('original_name', ''),
                'poster': format_poster(s.get('poster_path')),
                'backdrop': format_backdrop(s.get('backdrop_path') or s.get('poster_path')),
                'rating': round(s.get('vote_average', 0), 1),
                'tags': ['TMDB', str(s.get('first_air_date', ''))[:4] if s.get('first_air_date') else ''],
                'type': 'tv',
            }
            for s in data.get('similar', {}).get('results', [])[:10]
            if s.get('poster_path')
        ]
        return overview, cast, similar
    except Exception as e:
        print(f"⚠️ Fetch TMDB Series Meta Error: {e}")
        return "", [], []


# ==============================================================================
# 2. مسارات التشخيص والإعدادات
# ==============================================================================

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'status': 'online',
        'mode': 'Tiered Architecture (Phase 1) — TMDB-only metadata + Android-side scraping',
        'tls_impersonate': 'Chrome 124 (Active)' if HAS_CURL_CFFI else 'Standard Requests',
        'active_domains': {
            'akwam': AKWAM_BASE_DOMAIN,
            'larroza': LARROZA_BASE_DOMAIN,
        },
        'version': '13.1.0-ServerControl',
    })


@app.route('/api/test-redis', methods=['GET'])
def test_redis_debug():
    try:
        headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
        set_res = requests.post(
            UPSTASH_REDIS_REST_URL,
            json=["SET", "debug_test_key", "hello_redis", "EX", 60],
            headers=headers,
            timeout=3
        )
        get_res = requests.post(
            UPSTASH_REDIS_REST_URL,
            json=["GET", "debug_test_key"],
            headers=headers,
            timeout=3
        )
        return jsonify({
            "target_url": UPSTASH_REDIS_REST_URL,
            "set_status_code": set_res.status_code,
            "get_status_code": get_res.status_code,
            "connection_successful": (set_res.status_code == 200 and get_res.status_code == 200)
        })
    except Exception as e:
        return jsonify({"status": "error", "exception_message": str(e)}), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    akwam_headers = get_vault_session("akwam", AKWAM_BASE_DOMAIN)
    larroza_headers = get_vault_session("larroza", LARROZA_BASE_DOMAIN)
    moviz_headers = get_vault_session("moviz", "https://moviz-time.cfd")
    qfilm_headers = get_vault_session("qfilm", "https://a.qfilm.tv")

    return jsonify({
        'status': 'success',
        'version': '13.1.0-ServerControl',
        'providers': [

  {
                'name': 'free-movies',
                'domain': 'https://free-movies.world',
                'search_path': '/?s={query}',
                'catalog_path': '/movies?page={page}',
                'series_catalog_path': '/movies?page={page}',
                'card_selector': 'div.movie-item',
                'iframe_selector': 'iframe',
                'link_regex': r'''https?://[^\s"'<>]+\.(?:m3u8|mp4)[^\s"'<>]*''',
                'requires_unpack': False,
                'requires_webview': True,
                'active_headers': get_vault_session("free-movies", "https://free-movies.world"),
                'card_url_selector': 'a[href]',
                'card_title_selector': 'img[alt]',
                'card_poster_selector': 'img',
                'card_poster_attr': 'src',
                'match_threshold': 0.55,
                'extractor_script': r'''
                    (function() { return null; })();
                '''
            },



            




            
        ],
    })


# ==============================================================================
# 3. مسار الرئيسية (الأقسام الستة الغنية)
# ==============================================================================

@app.route('/api/home', methods=['GET'])
def get_home():
    CACHE_KEY = 'home_data_v7'
    cached = get_cached(CACHE_KEY)
    if cached is not None:
        return jsonify(cached)

    try:
        trending_movies = []
        trending_tv = []
        top_rated_movies = []
        action_movies = []
        family_animation = []
        kdrama_series = []

        try:
            m_res = requests.get(
                f'{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&language=ar-SA',
                headers=TMDB_HEADERS,
                timeout=2.5
            )
            if m_res.status_code == 200:
                trending_movies = [
                    {
                        'id': str(m.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(m.get('original_title') or m.get('title', '')))}",
                        'title': m.get('title') or m.get('original_title', ''),
                        'original_title': m.get('original_title', ''),
                        'poster': format_poster(m.get('poster_path')),
                        'backdrop': format_backdrop(m.get('backdrop_path') or m.get('poster_path')),
                        'rating': round(m.get('vote_average', 0), 1),
                        'tags': ['TMDB', str(m.get('release_date', ''))[:4] if m.get('release_date') else '2026'],
                        'type': 'movie',
                    }
                    for m in m_res.json().get('results', [])[:10]
                    if m.get('poster_path')
                ]
        except Exception as e:
            print(f"⚠️ Trending Movies Error: {e}")

        try:
            t_res = requests.get(
                f'{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&language=ar-SA',
                headers=TMDB_HEADERS,
                timeout=2.5
            )
            if t_res.status_code == 200:
                trending_tv = [
                    {
                        'id': str(t.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(t.get('original_name') or t.get('name', '')))}",
                        'title': t.get('name') or t.get('original_name', ''),
                        'original_title': t.get('original_name', ''),
                        'poster': format_poster(t.get('poster_path')),
                        'backdrop': format_backdrop(t.get('backdrop_path') or t.get('poster_path')),
                        'rating': round(t.get('vote_average', 0), 1),
                        'tags': ['TMDB', str(t.get('first_air_date', ''))[:4] if t.get('first_air_date') else '2026'],
                        'type': 'tv',
                    }
                    for t in t_res.json().get('results', [])[:10]
                    if t.get('poster_path')
                ]
        except Exception as e:
            print(f"⚠️ Trending TV Error: {e}")

        try:
            top_res = requests.get(
                f'{TMDB_BASE_URL}/movie/top_rated?api_key={TMDB_API_KEY}&language=ar-SA',
                headers=TMDB_HEADERS,
                timeout=2.5
            )
            if top_res.status_code == 200:
                top_rated_movies = [
                    {
                        'id': str(m.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(m.get('original_title') or m.get('title', '')))}",
                        'title': m.get('title') or m.get('original_title', ''),
                        'original_title': m.get('original_title', ''),
                        'poster': format_poster(m.get('poster_path')),
                        'backdrop': format_backdrop(m.get('backdrop_path') or m.get('poster_path')),
                        'rating': round(m.get('vote_average', 0), 1),
                        'tags': ['⭐ الأعلى تقييماً', str(m.get('release_date', ''))[:4] if m.get('release_date') else ''],
                        'type': 'movie',
                    }
                    for m in top_res.json().get('results', [])[:10]
                    if m.get('poster_path')
                ]
        except Exception as e:
            print(f"⚠️ Top Rated Error: {e}")

        try:
            action_url = f'{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_genres=28&sort_by=popularity.desc&language=ar-SA'
            action_res = requests.get(action_url, headers=TMDB_HEADERS, timeout=2.5)
            if action_res.status_code == 200:
                action_movies = [
                    {
                        'id': str(m.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(m.get('original_title') or m.get('title', '')))}",
                        'title': m.get('title') or m.get('original_title', ''),
                        'original_title': m.get('original_title', ''),
                        'poster': format_poster(m.get('poster_path')),
                        'backdrop': format_backdrop(m.get('backdrop_path') or m.get('poster_path')),
                        'rating': round(m.get('vote_average', 0), 1),
                        'tags': ['💥 أكشن', str(m.get('release_date', ''))[:4] if m.get('release_date') else ''],
                        'type': 'movie',
                    }
                    for m in action_res.json().get('results', [])[:10]
                    if m.get('poster_path')
                ]
        except Exception as e:
            print(f"⚠️ Action Movies Error: {e}")

        try:
            family_url = f'{TMDB_BASE_URL}/discover/movie?api_key={TMDB_API_KEY}&with_genres=16,10751&sort_by=popularity.desc&language=ar-SA'
            family_res = requests.get(family_url, headers=TMDB_HEADERS, timeout=2.5)
            if family_res.status_code == 200:
                family_animation = [
                    {
                        'id': str(m.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(m.get('original_title') or m.get('title', '')))}",
                        'title': m.get('title') or m.get('original_title', ''),
                        'original_title': m.get('original_title', ''),
                        'poster': format_poster(m.get('poster_path')),
                        'backdrop': format_backdrop(m.get('backdrop_path') or m.get('poster_path')),
                        'rating': round(m.get('vote_average', 0), 1),
                        'tags': ['🍿 عائلي', str(m.get('release_date', ''))[:4] if m.get('release_date') else ''],
                        'type': 'movie',
                    }
                    for m in family_res.json().get('results', [])[:10]
                    if m.get('poster_path')
                ]
        except Exception as e:
            print(f"⚠️ Family Animation Error: {e}")

        try:
            kdrama_url = f'{TMDB_BASE_URL}/discover/tv?api_key={TMDB_API_KEY}&with_original_language=ko&sort_by=popularity.desc&language=ar-SA'
            kdrama_res = requests.get(kdrama_url, headers=TMDB_HEADERS, timeout=2.5)
            if kdrama_res.status_code == 200:
                kdrama_series = [
                    {
                        'id': str(t.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(t.get('original_name') or t.get('name', '')))}",
                        'title': t.get('name') or t.get('original_name', ''),
                        'original_title': t.get('original_name', ''),
                        'poster': format_poster(t.get('poster_path')),
                        'backdrop': format_backdrop(t.get('backdrop_path') or t.get('poster_path')),
                        'rating': round(t.get('vote_average', 0), 1),
                        'tags': ['🌟 كوري', str(t.get('first_air_date', ''))[:4] if t.get('first_air_date') else ''],
                        'type': 'tv',
                    }
                    for t in kdrama_res.json().get('results', [])[:10]
                    if t.get('poster_path')
                ]
        except Exception as e:
            print(f"⚠️ KDrama Error: {e}")

        # v12.1 (Phase 1 — Tiered Architecture): Akwam fallback removed.
        # If TMDB returns empty trending lists (timeout/rate-limit),
        # the server simply returns empty sections — the Android app
        # handles empty data gracefully (no Akwam scraping on server).

        sections_list = [
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
            }
        ]

        if top_rated_movies:
            sections_list.append({
                'key': 'top_rated_movies',
                'title': '⭐ الأفلام الأعلى تقييماً',
                'has_see_all': False,
                'see_all_params': {},
                'items': top_rated_movies,
            })

        if action_movies:
            sections_list.append({
                'key': 'action_movies',
                'title': '💥 قمة الأكشن والإثارة',
                'has_see_all': False,
                'see_all_params': {},
                'items': action_movies,
            })

        if family_animation:
            sections_list.append({
                'key': 'family_animation',
                'title': '🍿 سينما العائلة والأنيميشن',
                'has_see_all': False,
                'see_all_params': {},
                'items': family_animation,
            })

        if kdrama_series:
            sections_list.append({
                'key': 'kdrama_series',
                'title': '🌟 أعمال حصرية / مسلسلات كورية',
                'has_see_all': False,
                'see_all_params': {},
                'items': kdrama_series,
            })

        result = {
            'status': 'success',
            'data': sections_list
        }

        set_cached(CACHE_KEY, result)
        return jsonify(result)

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==============================================================================
# 4. مسار الكتالوج والفلترة
# ==============================================================================

@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    """v12.1 (Phase 1 — Tiered Architecture): Catalog now comes from TMDB
    Discover instead of scraping Akwam. The Android app code is unchanged
    because the response shape is identical.

    Filter mapping (legacy Akwam sections → TMDB language filter):
      section=29 (Arabic)    → with_original_language=ar
      section=30 (Foreign)   → no filter (any non-Arabic falls through)
      section=31 (Indian)   → with_original_language=hi
      section=32 (Turkish)   → with_original_language=tr
      section=0  (All)       → no filter

    Cache TTL extended to 24h (was 6h) because catalog data is stable.
    """
    cat_type = request.args.get('type', 'movies').lower()  # movies | series
    page = request.args.get('page', '1')
    section = request.args.get('section', '')
    category = request.args.get('category', '')  # legacy: Akwam genre ID
    year = request.args.get('year', '')
    quality = request.args.get('quality', '')  # ignored — TMDB has no quality filter

    cache_key = f'catalog:{cat_type}:{page}:{section}:{category}:{year}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    tmdb_type = 'movie' if cat_type == 'movies' else 'tv'

    # Build TMDB Discover params
    discover_params = {
        'api_key': TMDB_API_KEY,
        'language': 'ar-SA',
        'page': page,
        'sort_by': 'popularity.desc',
        'include_adult': 'false',
    }

    # Section → with_original_language
    section_lang_map = {
        '29': 'ar',   # عربي
        '31': 'hi',   # هندي
        '32': 'tr',   # تركي
        # '30' (أجنبي) و '0' (الكل) → بدون فلتر لغة
    }
    if section in section_lang_map:
        discover_params['with_original_language'] = section_lang_map[section]

    # Category → with_genres (TMDB genre IDs)
    if category and category.isdigit():
        discover_params['with_genres'] = category

    # Year filter
    if year and year.isdigit():
        if tmdb_type == 'movie':
            discover_params['primary_release_date.gte'] = f'{year}-01-01'
            discover_params['primary_release_date.lte'] = f'{year}-12-31'
        else:
            discover_params['first_air_date.gte'] = f'{year}-01-01'
            discover_params['first_air_date.lte'] = f'{year}-12-31'

    try:
        discover_url = f'{TMDB_BASE_URL}/discover/{tmdb_type}'
        res = requests.get(discover_url, params=discover_params, headers=TMDB_HEADERS, timeout=4)
        if res.status_code != 200:
            return jsonify({'status': 'error', 'message': f'TMDB returned {res.status_code}'}), 502

        data = res.json()
        results = data.get('results', [])
        total_pages = data.get('total_pages', 1)
        current_page = data.get('page', int(page))

        # Build items with the same shape as /api/home and the old Akwam parser
        items = []
        for r in results:
            if not r.get('poster_path'):
                continue  # skip items without posters
            title = r.get('title') or r.get('name') or r.get('original_title') or 'غير متوفر'
            orig_title = r.get('original_title') or r.get('original_name') or ''
            date_field = r.get('release_date') or r.get('first_air_date') or ''
            year_tag = date_field[:4] if date_field else ''

            items.append({
                'id': str(r.get('id', '')),
                'title': title,
                'original_title': orig_title,
                'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(orig_title or title))}",
                'poster': format_poster(r.get('poster_path')),
                'backdrop': format_backdrop(r.get('backdrop_path') or r.get('poster_path')),
                'rating': round(r.get('vote_average', 0), 1),
                'tags': ['TMDB', year_tag] if year_tag else ['TMDB'],
                'type': 'movie' if tmdb_type == 'movie' else 'tv',
            })

        result = {
            'status': 'success',
            'data': {
                'type': cat_type,
                'filters': {
                    'section': section or 'all',
                    'category': category or 'all',
                    'year': year or 'all',
                    'quality': quality or 'all',
                },
                'current_page': current_page,
                'total_pages': total_pages,
                'has_next_page': current_page < total_pages,
                'items_count': len(items),
                'items': items,
            },
        }

        # v12.1: 24h cache for catalog (longer than 6h default — catalog is stable)
        set_cached(cache_key, result, ttl=24 * 3600)
        return jsonify(result)

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==============================================================================
# 5. مسار البحث الشامل عبر TMDB
# ==============================================================================

@app.route('/api/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    if not query:
        return jsonify({'status': 'error', 'message': 'Query missing'}), 400

    cache_key = f'search:{query.lower().strip()}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        search_url = f'{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={quote(query)}&language=ar-SA'
        res = requests.get(search_url, headers=TMDB_HEADERS, timeout=5)

        if res.status_code != 200:
            return jsonify({'status': 'success', 'data': []})

        items = []
        for item in res.json().get('results', []):
            m_type = item.get('media_type')
            if m_type in ['movie', 'tv']:
                vote_avg = item.get('vote_average')
                rating = round(vote_avg, 1) if isinstance(vote_avg, (int, float)) else 0.0

                title = item.get('title') or item.get('name') or item.get('original_title') or 'بدون عنوان'
                orig_title = item.get('original_name') or item.get('original_title') or ''
                poster_path = item.get('poster_path')

                raw_target = orig_title if orig_title else title
                search_target = clean_query_term(raw_target)

                sources = {
                    'akwam': f"{AKWAM_BASE_DOMAIN}/search?q={quote(search_target)}",
                    'larroza': f"{LARROZA_BASE_DOMAIN}/search.php?keywords={quote(search_target)}",
                    'moviz-time': f"https://moviz-time.cfd/?s={quote(search_target)}",
                    'qfilm': f"https://a.qfilm.tv/search.php?keywords={quote(search_target)}",
                }

                items.append({
                    'id': str(item.get('id', '')),
                    'url': sources['akwam'],
                    'sources': sources,
                    'title': title,
                    'original_title': orig_title,
                    'poster': format_poster(poster_path),
                    'backdrop': format_backdrop(item.get('backdrop_path') or poster_path),
                    'rating': rating,
                    'tags': ['TMDB'],
                    'type': m_type,
                })

        result = {'status': 'success', 'data': items}
        set_cached(cache_key, result)
        return jsonify(result)

    except Exception as e:
        print(f"⚠️ Search Error: {e}")
        return jsonify({'status': 'success', 'data': []})


# ==============================================================================
# 6. مسار تفاصيل المسلسلات (TMDB-First Architecture)
# ==============================================================================

@app.route('/api/series-details', methods=['GET'])
def get_series_details():
    series_url = request.args.get('url', '').strip()
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()
    orig_title = request.args.get('original_title', '').strip()
    selected_season = request.args.get('season', '1').strip()
    target_year = request.args.get('year', '').strip()

    # استخراج TMDB ID أولاً لضمان الاعتماد على قاعدة البيانات العالمية
    clean_tmdb_id = resolve_tmdb_tv_id(tmdb_id or series_url, title=title, orig_title=orig_title)

    cache_key = f'series:v3:{clean_tmdb_id or series_url}:{selected_season}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    # ══════════════════════════════════════════════════════════════════════════
    # المسار الأساسي 1: بناء بنية المسلسل كاملة عبر TMDB (يمنع أي Mismatch)
    # ══════════════════════════════════════════════════════════════════════════
    if clean_tmdb_id:
        try:
            tmdb_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}?api_key={TMDB_API_KEY}&language=ar-SA&append_to_response=credits,similar'
            res_tv_obj = requests.get(tmdb_url, headers=TMDB_HEADERS, timeout=4)
            if res_tv_obj.status_code == 200:
                res_tv = res_tv_obj.json()

                tv_title = res_tv.get('name') or title or 'مسلسل'
                tv_orig_title = res_tv.get('original_name') or orig_title or tv_title
                overview = res_tv.get('overview', '')

                # طاقم التمثيل بالصور الحقيقية
                cast = [
                    {
                        'name': c.get('name', ''),
                        'character': c.get('character', ''),
                        'profile': format_profile(c.get('profile_path')),
                    }
                    for c in res_tv.get('credits', {}).get('cast', [])[:10]
                ]

                # المسلسلات المشابهة
                similar = [
                    {
                        'id': str(s.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(s.get('original_name') or s.get('name', '')))}",
                        'title': s.get('name') or s.get('original_name', ''),
                        'original_title': s.get('original_name', ''),
                        'poster': format_poster(s.get('poster_path')),
                        'backdrop': format_backdrop(s.get('backdrop_path') or s.get('poster_path')),
                        'rating': round(s.get('vote_average', 0), 1),
                        'tags': ['TMDB', str(s.get('first_air_date', ''))[:4] if s.get('first_air_date') else ''],
                        'type': 'tv',
                    }
                    for s in res_tv.get('similar', {}).get('results', [])[:10]
                    if s.get('poster_path')
                ]

                # قائمة المواسم
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

                # صياغة استعلامات بحث ذكية وموحدة للحلقات
                episodes = []
                clean_base_title = clean_query_term(tv_title)
                clean_base_orig = clean_query_term(tv_orig_title)

                for ep in res_ep.get('episodes', []):
                    ep_num = ep.get('episode_number')
                    episodes.append({
                        'season_number': season_num,
                        'episode_number': ep_num,
                        'title': f"الحلقة {ep_num} - {ep.get('name', '')}",
                        'search_title': f"{clean_base_title} الموسم {season_num} الحلقة {ep_num}",
                        'search_orig_title': f"{clean_base_orig} S{season_num:02d}E{ep_num:02d}",
                    })

                res_data = {
                    'status': 'success',
                    'data': {
                        'current_season': season_num,
                        'seasons': seasons,
                        'episodes': episodes,
                        'overview': overview,
                        'cast': cast,
                        'similar': similar,
                    },
                }
                set_cached(cache_key, res_data)
                return jsonify(res_data)
        except Exception as tmdb_err:
            print(f'⚠️ TMDB Primary Architecture Error: {tmdb_err}')

    # v12.1 (Phase 1 — Tiered Architecture): Akwam fallback removed.
    # When TMDB can't resolve the show, the server returns empty episodes.
    # The Android app detects this and scrapes Akwam locally on the user's
    # device via GenericScraper.scrapeSeriesFallback().
    return jsonify({
        'status': 'success',
        'data': {
            'current_season': 1,
            'seasons': [],
            'episodes': [],
            'overview': '',
            'cast': [],
            'similar': [],
        },
        'message': 'لم يتم العثور على حلقات لهذا المسلسل',
    })


# ==============================================================================
# 7. مسار تفاصيل الأفلام (مع صور الممثلين الحقيقية profile والأفلام المشابهة)
# ==============================================================================

@app.route('/api/movie-details', methods=['GET'])
def get_movie_details():
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()

    cache_key = f'movie:v2:{tmdb_id or title}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    clean_id = None
    if tmdb_id and tmdb_id.isdigit():
        clean_id = tmdb_id
    elif title:
        try:
            search_url = f'{TMDB_BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={quote(clean_query_term(title))}&language=ar-SA'
            res = requests.get(search_url, headers=TMDB_HEADERS, timeout=4)
            if res.status_code == 200:
                results = res.json().get('results', [])
                if results:
                    clean_id = str(results[0].get('id', ''))
        except Exception:
            pass

    if not clean_id:
        return jsonify({
            'status': 'success',
            'data': None,
            'message': 'لم يتم العثور على تفاصيل',
        })

    try:
        detail_url = f'{TMDB_BASE_URL}/movie/{clean_id}?api_key={TMDB_API_KEY}&language=ar-SA&append_to_response=credits,videos,similar'
        res = requests.get(detail_url, headers=TMDB_HEADERS, timeout=4)
        if res.status_code != 200:
            return jsonify({'status': 'success', 'data': None})

        data = res.json()
        result = {
            'status': 'success',
            'data': {
                'id': str(data.get('id', '')),
                'title': data.get('title', ''),
                'original_title': data.get('original_title', ''),
                'overview': data.get('overview', ''),
                'release_date': data.get('release_date', ''),
                'runtime': data.get('runtime', 0),
                'rating': round(data.get('vote_average', 0), 1),
                'poster': format_poster(data.get('poster_path')),
                'backdrop': format_backdrop(data.get('backdrop_path')),
                'genres': [g.get('name', '') for g in data.get('genres', [])],
                'cast': [
                    {
                        'name': c.get('name', ''),
                        'character': c.get('character', ''),
                        'profile': format_profile(c.get('profile_path')),
                    }
                    for c in data.get('credits', {}).get('cast', [])[:10]
                ],
                'videos': [
                    {
                        'key': v.get('key', ''),
                        'name': v.get('name', ''),
                        'site': v.get('site', ''),
                        'type': v.get('type', ''),
                    }
                    for v in data.get('videos', {}).get('results', [])[:5]
                ],
                'similar': [
                    {
                        'id': str(s.get('id', '')),
                        'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(s.get('original_title') or s.get('title', '')))}",
                        'title': s.get('title') or s.get('original_title', ''),
                        'original_title': s.get('original_title', ''),
                        'poster': format_poster(s.get('poster_path')),
                        'backdrop': format_backdrop(s.get('backdrop_path') or s.get('poster_path')),
                        'rating': round(s.get('vote_average', 0), 1),
                        'tags': ['TMDB', str(s.get('release_date', ''))[:4] if s.get('release_date') else ''],
                        'type': 'movie',
                    }
                    for s in data.get('similar', {}).get('results', [])[:10]
                    if s.get('poster_path')
                ],
            },
        }

        set_cached(cache_key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==============================================================================
# 8. كاش صفحات المشاهدة المشترك (v2)
# ==============================================================================

@app.route('/api/page-cache', methods=['GET', 'POST'])
def handle_page_cache():
    if request.method == 'GET':
        cache_key = request.args.get('key')
        if not cache_key:
            return jsonify({'status': 'error', 'message': 'Missing key'}), 400

        cached_url = get_cached(f"page:v2:{cache_key}")
        return jsonify({'status': 'success', 'url': cached_url})

    elif request.method == 'POST':
        data = request.get_json(silent=True) or {}
        cache_key = data.get('key')
        target_url = data.get('url')

        if cache_key and target_url:
            set_cached(f"page:v2:{cache_key}", target_url, ttl=48 * 3600)
            return jsonify({'status': 'success', 'message': 'Cached successfully'})

        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
