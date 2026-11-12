
import os
import time
from concurrent.futures import ThreadPoolExecutor
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

# تأمين المفاتيح عبر متغيرات البيئة في Vercel مع الإبقاء على القيم الافتراضية كاحتياط
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '65687d1e167bc35f38ee0c88c3a37b74')
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

# ==============================================================================
# ⚡ Upstash Redis Configuration
# ==============================================================================

UPSTASH_REDIS_REST_URL = os.environ.get('UPSTASH_REDIS_REST_URL', 'https://immortal-redfish-188577.upstash.io')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', 'gQAAAAAAAuChAAIgcDI2MGIzYmQwZTdhYTQ0Y2MxYjFmZTU1YjU2ZGMyNGI0Mw')
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
# v3.1.47 — لغة محتوى السينما (توجيه المالك: لغة المحتوى تتبع لغة التطبيق)
# التطبيق يرسل lang=en-US عندما يكون بالإنجليزية وlang=ar-SA عندما يكون
# بالعربية؛ الغياب أو أي قيمة أخرى → ar-SA (السلوك الأصلي حرفياً).
# ==============================================================================

def normalize_lang(raw):
    """en / en-US / en-GB → en-US؛ أي شيء آخر (أو غياب) → ar-SA."""
    if raw and str(raw).strip().lower().startswith('en'):
        return 'en-US'
    return 'ar-SA'


def is_en(lang):
    return lang == 'en-US'


# v3.1.47+ — أسماء الأقسام المعروفة بالإنجليزية (نفس مفاتيح الأقسام؛
# العربية تبقى عناوين السيرفر الحرفية).
EN_SECTION_TITLES = {
    'trending_movies': 'Popular Movies',
    'now_playing_movies': 'Now Playing in Cinema',
    'top_rated_movies': 'Top Rated Movies',
    'action_movies': 'Action & Thriller',
    'scifi_fantasy_movies': 'Sci-Fi & Fantasy',
    'horror_mystery_movies': 'Horror & Mystery',
    'comedy_movies': 'Comedy Movies',
    'drama_crime_movies': 'Drama & Crime',
    'family_animation': 'Family & Animation',
    'arabic_movies': 'Arabic Movies',
    'trending_tv': 'Popular Series',
    'top_rated_tv': 'Top Rated Series',
    'action_scifi_tv': 'Action & Sci-Fi Series',
    'crime_drama_tv': 'Crime & Drama Series',
    'anime_animation_tv': 'Anime & Animation',
    'kdrama_series': 'K-Drama Series',
    'turkish_series': 'Turkish Series',
    'arabic_series': 'Arabic Series',
}

# v3.1.47+ — بطاقات الوسوم (التصنيف المصغّر على البطاقة) بلغة الطلب.
def section_tag(ar_tag, lang):
    """وسم البطاقة بلغة المحتوى (⭐ الأعلى تقييماً → ⭐ Top Rated …)."""
    if not is_en(lang):
        return ar_tag
    return {
        '⭐ الأعلى تقييماً': '⭐ Top Rated',
        '🎬 يعرض الآن': '🎬 Now Playing',
        '💥 أكشن': '💥 Action',
        '🚀 خيال علمي': '🚀 Sci-Fi',
        '👻 رعب': '👻 Horror',
        '😂 كوميديا': '😂 Comedy',
        '🎭 دراما': '🎭 Drama',
        '🍿 عائلي': '🍿 Family',
        '🇪🇬 عربي': '🇪🇬 Arabic',
        '🏆 مميز': '🏆 Top Series',
        '⚡ مغامرة': '⚡ Adventure',
        '🕵️ جريمة': '🕵️ Crime',
        '🎌 أنمي': '🎌 Anime',
        '🌟 كوري': '🌟 Korean',
        '🇹🇷 تركي': '🇹🇷 Turkish',
        '🌙 عربي': '🌙 Arabic',
    }.get(ar_tag, ar_tag)


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


def resolve_tmdb_tv_id(candidate_id, title=None, orig_title=None, lang='ar-SA'):
    """استخراج أو البحث عن معرّف المسلسل الرقمي في TMDB بدقة عالية."""
    if candidate_id and str(candidate_id).strip().isdigit():
        return str(candidate_id).strip()

    search_queries = [orig_title, title]
    for q in search_queries:
        if not q:
            continue
        try:
            cleaned = clean_query_term(q)
            s_url = f'{TMDB_BASE_URL}/search/tv?api_key={TMDB_API_KEY}&query={quote(cleaned)}&language={normalize_lang(lang)}'
            s_res = requests.get(s_url, headers=TMDB_HEADERS, timeout=3.5)
            if s_res.status_code == 200:
                results = s_res.json().get('results', [])
                if results:
                    return str(results[0].get('id'))
        except Exception as e:
            print(f"⚠️ Search TMDB TV ID Error for '{q}': {e}")
    return None


def fetch_tmdb_series_meta(clean_tmdb_id, lang='ar-SA'):
    """جلب القصة والممثلين بالصور والمسلسلات المشابهة من TMDB."""
    if not clean_tmdb_id:
        return "", [], []

    try:
        t_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}?api_key={TMDB_API_KEY}&language={normalize_lang(lang)}&append_to_response=credits,similar'
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
        'version': '13.2.0-RichCatalog',
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
        'version': '13.2.0-RichCatalog',
        'providers': [
            {
                'name': 'akwam',
                'domain': AKWAM_BASE_DOMAIN,
                'search_path': '/search?q={query}',
                'catalog_path': '/movies?page={page}&section={section}',
                'series_catalog_path': '/series?page={page}&section={section}',
                'card_selector': 'div.entry-box',
                'movie_selector': 'a[href*=/movie/]',
                'series_selector': 'a[href*=/series/]',
                'ep_selector': 'a[href*=/episode/]',
                'watch_selector': 'a[href*=/watch/], a.link-btn',
                'link_regex': r'https?://[^\s"\'<>]+\.(?:mp4)[^\s"\'<>]*',
                'requires_unpack': False,
                'active_headers': akwam_headers,
                # v13.1: Server-controllable extraction fields
                'card_url_selector': 'a[href]',
                'card_title_selector': 'img[alt]',
                'card_poster_selector': 'img',
                'card_poster_attr': 'data-src',
                'match_threshold': 0.65,
                'extractor_script': r"""
                    (function() {
                        var match = __HTML__.match(/https?:\/\/[^\s"'<>]+\.(?:mp4)[^\s"'<>]*/i);
                        if (match) {
                            return {
                                url: match[0],
                                referer: __PAGE_URL__,
                                quality: '1080p FHD'
                            };
                        }
                        return null;
                    })();
                """
            },
            {
                'name': 'larroza',
                'domain': LARROZA_BASE_DOMAIN,
                'search_path': '/search.php?keywords={query}',
                'catalog_path': '/newvideos1.php?page={page}',
                'series_catalog_path': '/moslslat4.php?page={page}',
                'card_selector': 'a[href*=video.php]',
                'iframe_selector': 'iframe',
                'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
                'requires_unpack': True,
                'active_headers': larroza_headers,
                # v13.1: Server-controllable extraction fields
                'card_url_selector': 'a[href]',
                'card_title_selector': 'img[alt]',
                'card_poster_selector': 'img',
                'card_poster_attr': 'data-echo',
                'match_threshold': 0.55,
                'extractor_script': r"""
                    (function() {
                        var match = __HTML__.match(/https?:\/\/[^\s"'<>]+\.(?:m3u8|mp4)[^\s"'<>]*/i);
                        if (match) {
                            return {
                                url: match[0],
                                referer: __PAGE_URL__,
                                quality: match[0].indexOf('.m3u8') !== -1 ? 'HLS' : '1080p'
                            };
                        }
                        return null;
                    })();
                """
            },
            {
                # v12.3: Moviz-Time re-enabled with requires_webview=true.
                # FirePlayer JS generates the stream URL at runtime via vhash.
                # We load the iframe page in a hidden WebView, let FirePlayer
                # + JWPlayer initialize naturally, and intercept the actual
                # m3u8 URL via shouldInterceptRequest. This is the universal
                # approach for ANY JS-driven player framework.
                'name': 'moviz-time',
                'domain': 'https://moviz-time.cfd',
                'search_path': '/?s={query}',
                'card_selector': 'article.pinbox .thumb a, h2.title-2 a, h3.title-2 a, article.pinbox a[href]',
                'iframe_selector': 'iframe, iframe[data-src], [data-src], [data-url], [data-link]',
                'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4|txt)[^\s"\'<>]*',
                'requires_unpack': False,
                'ajax_required': False,
                'requires_webview': True,  # ← v12.3: uses JsStreamExtractor
                'series_selector': 'article.pinbox a[href]',
                'active_headers': moviz_headers,
                'extractor_script': r"""
                    (function() {
                        var match = __HTML__.match(/https?:\/\/[^\s"'<>]+\.(?:m3u8|mp4|txt)[^\s"'<>]*/i);
                        if (match) {
                            return {
                                url: match[0],
                                referer: __PAGE_URL__,
                                quality: 'Auto'
                            };
                        }
                        return null;
                    })();
                """
            },
            {
                'name': 'qfilm',
                'domain': 'https://a.qfilm.tv',
                'search_path': '/search.php?keywords={query}',
                'catalog_path': '/browse.php?page={page}',
                'series_catalog_path': '/moslslat.php?page={page}',
                'card_selector': 'ul.pm-ul-browse-videos a[href*="watch.php"], .pm-li-video a[href*="watch.php"], .pm-video-thumb a[href*="watch.php"], .pm-search-results a[href*="watch.php"]',
                'movie_selector': 'ul.pm-ul-browse-videos a[href*="watch.php"], .pm-li-video a[href*="watch.php"], .pm-video-thumb a[href*="watch.php"]',
                'series_selector': 'a[href*="series.php"], a[href*="watch.php"]',
                # v13.1: Server-controllable extraction fields
                'card_url_selector': 'a[href]',
                'card_title_selector': 'h3.caption, img[alt]',
                'card_poster_selector': 'img',
                'card_poster_attr': 'data-echo',
                'match_threshold': 0.55,
                # v12.2.7: QFilm iframe_selector updated to include option[value]
                'iframe_selector': 'iframe, option[value]',
                'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
                'ajax_required': True,
                'requires_unpack': False,
                'active_headers': qfilm_headers,
                'extractor_script': r"""
                    (function() {
                        var match = __HTML__.match(/https?:\/\/[^\s"'<>]+\.(?:m3u8|mp4)[^\s"'<>]*/i);
                        if (match) {
                            return {
                                url: match[0],
                                referer: __PAGE_URL__,
                                quality: 'HD'
                            };
                        }
                        return null;
                    })();
                """
            },
        ],
    })


# ==============================================================================
# 3. مسار الرئيسية (الأقسام الثمانية عشر الغنية — 20 عملاً لكل قسم)
# ==============================================================================

def _fetch_tmdb_section_items(endpoint, media_type, lang, badge_ar=None, limit=20):
    """جلب قائمة أفلام أو مسلسلات من TMDB وتنسيقها بنفس بنية التطبيق."""
    try:
        sep = '&' if '?' in endpoint else '?'
        url = f'{TMDB_BASE_URL}{endpoint}{sep}api_key={TMDB_API_KEY}&language={lang}'
        res = requests.get(url, headers=TMDB_HEADERS, timeout=3.5)
        if res.status_code != 200:
            return []

        items = []
        is_movie = (media_type == 'movie')
        for row in res.json().get('results', [])[:limit]:
            if not row.get('poster_path'):
                continue
            title = (
                row.get('title') or row.get('name')
                or row.get('original_title') or row.get('original_name') or ''
            )
            orig_title = row.get('original_title') or row.get('original_name') or ''
            date_val = row.get('release_date') if is_movie else row.get('first_air_date')
            year_str = str(date_val)[:4] if date_val else '2026'
            primary_tag = section_tag(badge_ar, lang) if badge_ar else 'TMDB'

            items.append({
                'id': str(row.get('id', '')),
                'url': f"{AKWAM_BASE_DOMAIN}/search?q={quote(clean_query_term(orig_title or title))}",
                'title': title,
                'original_title': orig_title,
                'poster': format_poster(row.get('poster_path')),
                'backdrop': format_backdrop(row.get('backdrop_path') or row.get('poster_path')),
                'rating': round(row.get('vote_average', 0), 1),
                'tags': [primary_tag, year_str] if year_str else [primary_tag],
                'type': 'movie' if is_movie else 'tv',
            })
        return items
    except Exception as e:
        print(f"⚠️ Home Section Fetch Error ({endpoint}): {e}")
        return []


@app.route('/api/home', methods=['GET'])
def get_home():
    # v3.1.47+ — لغة المحتوى (lang من التطبيق؛ الافتراضي ar-SA كما كان).
    lang = normalize_lang(request.args.get('lang', ''))
    CACHE_KEY = f'home_data_v8:{lang}'
    cached = get_cached(CACHE_KEY)
    if cached is not None:
        return jsonify(cached)

    try:
        section_specs = [
            # ── أقسام الأفلام (10 أقسام × 20 فيلماً) ──
            ('trending_movies', '🔥 الأفلام الأكثر شهرة', True, {'type': 'movies', 'page': 1},
             '/trending/movie/week', 'movie', None),
            ('now_playing_movies', '🎬 يعرض الآن في السينما', False, {},
             '/movie/now_playing', 'movie', '🎬 يعرض الآن'),
            ('top_rated_movies', '⭐ الأفلام الأعلى تقييماً', False, {},
             '/movie/top_rated', 'movie', '⭐ الأعلى تقييماً'),
            ('action_movies', '💥 قمة الأكشن والإثارة', False, {},
             '/discover/movie?with_genres=28,53&sort_by=popularity.desc', 'movie', '💥 أكشن'),
            ('scifi_fantasy_movies', '🚀 خيال علمي وفانتازيا', False, {},
             '/discover/movie?with_genres=878,14&sort_by=popularity.desc', 'movie', '🚀 خيال علمي'),
            ('horror_mystery_movies', '👻 رعب وغموض', False, {},
             '/discover/movie?with_genres=27,9648&sort_by=popularity.desc', 'movie', '👻 رعب'),
            ('comedy_movies', '😂 أفلام الكوميديا', False, {},
             '/discover/movie?with_genres=35&sort_by=popularity.desc', 'movie', '😂 كوميديا'),
            ('drama_crime_movies', '🎭 دراما وجريمة', False, {},
             '/discover/movie?with_genres=18,80&sort_by=popularity.desc', 'movie', '🎭 دراما'),
            ('family_animation', '🍿 سينما العائلة والأنيميشن', False, {},
             '/discover/movie?with_genres=16,10751&sort_by=popularity.desc', 'movie', '🍿 عائلي'),
            ('arabic_movies', '🇪🇬 أفلام عربية', False, {},
             '/discover/movie?with_original_language=ar&sort_by=popularity.desc', 'movie', '🇪🇬 عربي'),

            # ── أقسام المسلسلات (8 أقسام × 20 مسلسلاً) ──
            ('trending_tv', '📺 المسلسلات الأكثر مشاهدة', True, {'type': 'series', 'page': 1},
             '/trending/tv/week', 'tv', None),
            ('top_rated_tv', '🏆 المسلسلات الأعلى تقييماً', False, {},
             '/tv/top_rated', 'tv', '🏆 مميز'),
            ('action_scifi_tv', '⚡ مسلسلات أكشن وخيال علمي', False, {},
             '/discover/tv?with_genres=10759,10765&sort_by=popularity.desc', 'tv', '⚡ مغامرة'),
            ('crime_drama_tv', '🕵️ مسلسلات جريمة ودراما', False, {},
             '/discover/tv?with_genres=80,18&sort_by=popularity.desc', 'tv', '🕵️ جريمة'),
            ('anime_animation_tv', '🎌 أنمي وكرتون', False, {},
             '/discover/tv?with_genres=16&sort_by=popularity.desc', 'tv', '🎌 أنمي'),
            ('kdrama_series', '🌟 أعمال حصرية / مسلسلات كورية', False, {},
             '/discover/tv?with_original_language=ko&sort_by=popularity.desc', 'tv', '🌟 كوري'),
            ('turkish_series', '🇹🇷 مسلسلات تركية', False, {},
             '/discover/tv?with_original_language=tr&sort_by=popularity.desc', 'tv', '🇹🇷 تركي'),
            ('arabic_series', '🌙 مسلسلات عربية', False, {},
             '/discover/tv?with_original_language=ar&sort_by=popularity.desc', 'tv', '🌙 عربي'),
        ]

        # جلب جميع الأقسام بالتوازي لتسريع الاستجابة على Vercel (< 1.5 ثانية)
        fetched_items = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(
                    _fetch_tmdb_section_items,
                    spec[4], spec[5], lang, spec[6], 20
                ): spec[0]
                for spec in section_specs
            }
            for fut in futures:
                sec_key = futures[fut]
                try:
                    fetched_items[sec_key] = fut.result()
                except Exception:
                    fetched_items[sec_key] = []

        sections_list = []
        for key, ar_title, has_see_all, see_all_params, _, _, _ in section_specs:
            items = fetched_items.get(key, [])
            if items or key in ('trending_movies', 'trending_tv'):
                sections_list.append({
                    'key': key,
                    'title': ar_title,
                    'has_see_all': has_see_all,
                    'see_all_params': see_all_params,
                    'items': items,
                })

        # v3.1.47 — أسماء الأقسام بلغة الطلب (المفاتيح المعروفة فقط؛
        # أي قسم جديد من السيرفر يبقى بعنوانه الأصلي دون تحديث التطبيق).
        if is_en(lang):
            for s in sections_list:
                if s.get('key') in EN_SECTION_TITLES:
                    s['title'] = EN_SECTION_TITLES[s['key']]

        result = {
            'status': 'success',
            'data': sections_list
        }

        set_cached(CACHE_KEY, result)
        return jsonify(result)

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==============================================================================
# 4. مسار الكتالوج والفلترة (مضاعف: يجلب صفحتين = 40 عنصراً لكل طلب)
# ==============================================================================

@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    """v13.2 (Rich Catalog): Catalog comes from TMDB Discover.
    Each requested page fetches 2 consecutive TMDB pages (40 items) in parallel
    so the app's 3-page injection loads ~120 latest movies + ~120 latest series.

    Filter mapping (legacy Akwam sections → TMDB language filter):
      section=29 (Arabic)    → with_original_language=ar
      section=30 (Foreign)   → no filter (any non-Arabic falls through)
      section=31 (Indian)   → with_original_language=hi
      section=32 (Turkish)   → with_original_language=tr
      section=0  (All)       → no filter
    """
    cat_type = request.args.get('type', 'movies').lower()  # movies | series
    page = request.args.get('page', '1')
    section = request.args.get('section', '')
    category = request.args.get('category', '')  # legacy: Akwam genre ID
    year = request.args.get('year', '')
    quality = request.args.get('quality', '')  # ignored — TMDB has no quality filter
    # v3.1.47 — لغة المحتوى (توجيه المالك) + مفتاح كاش لكل لغة.
    lang = normalize_lang(request.args.get('lang', ''))

    cache_key = f'catalog:v2:{cat_type}:{page}:{section}:{category}:{year}:{lang}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    tmdb_type = 'movie' if cat_type == 'movies' else 'tv'
    page_int = int(page) if str(page).isdigit() and int(page) > 0 else 1

    # Build TMDB Discover base params
    base_params = {
        'api_key': TMDB_API_KEY,
        'language': lang,
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
        base_params['with_original_language'] = section_lang_map[section]

    # Category → with_genres (TMDB genre IDs)
    if category and category.isdigit():
        base_params['with_genres'] = category

    # Year filter
    if year and year.isdigit():
        if tmdb_type == 'movie':
            base_params['primary_release_date.gte'] = f'{year}-01-01'
            base_params['primary_release_date.lte'] = f'{year}-12-31'
        else:
            base_params['first_air_date.gte'] = f'{year}-01-01'
            base_params['first_air_date.lte'] = f'{year}-12-31'

    def _fetch_discover_page(tmdb_page_num):
        params = dict(base_params)
        params['page'] = str(tmdb_page_num)
        discover_url = f'{TMDB_BASE_URL}/discover/{tmdb_type}'
        return requests.get(discover_url, params=params, headers=TMDB_HEADERS, timeout=4)

    try:
        tmdb_p1 = (page_int - 1) * 2 + 1
        tmdb_p2 = tmdb_p1 + 1

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_fetch_discover_page, tmdb_p1)
            f2 = executor.submit(_fetch_discover_page, tmdb_p2)
            res1 = f1.result()
            res2 = f2.result()

        if res1.status_code != 200:
            return jsonify({'status': 'error', 'message': f'TMDB returned {res1.status_code}'}), 502

        data1 = res1.json()
        raw_results = list(data1.get('results', []))
        if res2.status_code == 200:
            raw_results.extend(res2.json().get('results', []))

        raw_total_pages = data1.get('total_pages', 1)
        total_pages = max(1, (raw_total_pages + 1) // 2)
        current_page = page_int

        # Build items with the same shape as /api/home and the old Akwam parser
        items = []
        seen_ids = set()
        for r in raw_results:
            if not r.get('poster_path'):
                continue  # skip items without posters
            item_id = str(r.get('id', ''))
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            title = r.get('title') or r.get('name') or r.get('original_title') or (
                'Unavailable' if is_en(lang) else 'غير متوفر')
            orig_title = r.get('original_title') or r.get('original_name') or ''
            date_field = r.get('release_date') or r.get('first_air_date') or ''
            year_tag = date_field[:4] if date_field else ''

            items.append({
                'id': item_id,
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

    # v3.1.47 — لغة المحتوى + مفتاح كاش لكل لغة.
    lang = normalize_lang(request.args.get('lang', ''))
    cache_key = f'search:{query.lower().strip()}:{lang}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        search_url = f'{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={quote(query)}&language={lang}'
        res = requests.get(search_url, headers=TMDB_HEADERS, timeout=5)

        if res.status_code != 200:
            return jsonify({'status': 'success', 'data': []})

        items = []
        for item in res.json().get('results', []):
            m_type = item.get('media_type')
            if m_type in ['movie', 'tv']:
                vote_avg = item.get('vote_average')
                rating = round(vote_avg, 1) if isinstance(vote_avg, (int, float)) else 0.0

                title = item.get('title') or item.get('name') or item.get('original_title') or (
                    'Untitled' if is_en(lang) else 'بدون عنوان')
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
    # v3.1.47 — لغة المحتوى + مفتاح كاش لكل لغة.
    lang = normalize_lang(request.args.get('lang', ''))

    # استخراج TMDB ID أولاً لضمان الاعتماد على قاعدة البيانات العالمية
    clean_tmdb_id = resolve_tmdb_tv_id(tmdb_id or series_url, title=title, orig_title=orig_title, lang=lang)

    cache_key = f'series:v3:{clean_tmdb_id or series_url}:{selected_season}:{lang}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    # ══════════════════════════════════════════════════════════════════════════
    # المسار الأساسي 1: بناء بنية المسلسل كاملة عبر TMDB (يمنع أي Mismatch)
    # ══════════════════════════════════════════════════════════════════════════
    if clean_tmdb_id:
        try:
            tmdb_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}?api_key={TMDB_API_KEY}&language={lang}&append_to_response=credits,similar'
            res_tv_obj = requests.get(tmdb_url, headers=TMDB_HEADERS, timeout=4)
            if res_tv_obj.status_code == 200:
                res_tv = res_tv_obj.json()

                tv_title = res_tv.get('name') or title or ('Series' if is_en(lang) else 'مسلسل')
                tv_orig_title = res_tv.get('original_name') or orig_title or tv_title
                # v3.1.47 — قانون الرجوع للإنجليزية (توجيه المالك حرفياً):
                # وصف عربي فارغ على TMDB → نستعير الوصف الإنجليزي بدل الفراغ.
                overview = res_tv.get('overview', '')
                if not is_en(lang) and not overview.strip():
                    try:
                        fb_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}?api_key={TMDB_API_KEY}&language=en-US'
                        fb_res = requests.get(fb_url, headers=TMDB_HEADERS, timeout=4)
                        if fb_res.status_code == 200:
                            overview = fb_res.json().get('overview', '') or overview
                    except Exception:
                        pass

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
                            'title': s.get('name') or (
                                f'Season {s_num}' if is_en(lang) else f'الموسم {s_num}'),
                            'episode_count': s.get('episode_count', 0),
                        })

                season_num = int(selected_season) if selected_season.isdigit() else 1
                ep_url = f'{TMDB_BASE_URL}/tv/{clean_tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}&language={lang}'
                res_ep = requests.get(ep_url, headers=TMDB_HEADERS, timeout=4).json()

                # صياغة استعلامات بحث ذكية وموحدة للحلقات
                episodes = []
                clean_base_title = clean_query_term(tv_title)
                clean_base_orig = clean_query_term(tv_orig_title)

                for ep in res_ep.get('episodes', []):
                    ep_num = ep.get('episode_number')
                    # v3.1.47 — عنوان الحلقة المعروض بلغة المحتوى؛
                    # search_title/search_orig_title يبقيان بصيغتهما
                    # العربية/اللاتينية (استعلامات مواقع المزودين).
                    ep_display = f"Episode {ep_num} - {ep.get('name', '')}" if is_en(lang) \
                        else f"الحلقة {ep_num} - {ep.get('name', '')}"
                    episodes.append({
                        'season_number': season_num,
                        'episode_number': ep_num,
                        'title': ep_display,
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
    # v3.1.47 — لغة المحتوى + مفتاح كاش لكل لغة.
    lang = normalize_lang(request.args.get('lang', ''))

    cache_key = f'movie:v2:{tmdb_id or title}:{lang}'
    cached = get_cached(cache_key)
    if cached is not None:
        return jsonify(cached)

    clean_id = None
    if tmdb_id and tmdb_id.isdigit():
        clean_id = tmdb_id
    elif title:
        try:
            search_url = f'{TMDB_BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={quote(clean_query_term(title))}&language={lang}'
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
        detail_url = f'{TMDB_BASE_URL}/movie/{clean_id}?api_key={TMDB_API_KEY}&language={lang}&append_to_response=credits,videos,similar'
        res = requests.get(detail_url, headers=TMDB_HEADERS, timeout=4)
        if res.status_code != 200:
            return jsonify({'status': 'success', 'data': None})

        data = res.json()
        # v3.1.47 — قانون الرجوع للإنجليزية (توجيه المالك حرفياً): وصف
        # عربي فارغ على TMDB → نستعير الوصف الإنجليزي بدل الفراغ.
        overview = data.get('overview', '')
        if not is_en(lang) and not overview.strip():
            try:
                fb_url = f'{TMDB_BASE_URL}/movie/{clean_id}?api_key={TMDB_API_KEY}&language=en-US&append_to_response=credits,videos,similar'
                fb_res = requests.get(fb_url, headers=TMDB_HEADERS, timeout=4)
                if fb_res.status_code == 200:
                    overview = fb_res.json().get('overview', '') or overview
            except Exception:
                pass
        result = {
            'status': 'success',
            'data': {
                'id': str(data.get('id', '')),
                'title': data.get('title', ''),
                'original_title': data.get('original_title', ''),
                'overview': overview,
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
# 8. كاش صفحات المشاهدة والروابط المشترك (v2 — يدعم Referer وتفادي 403)
# ==============================================================================

@app.route('/api/page-cache', methods=['GET', 'POST'])
def handle_page_cache():
    if request.method == 'GET':
        cache_key = request.args.get('key')
        if not cache_key:
            return jsonify({'status': 'error', 'message': 'Missing key'}), 400

        cached_data = get_cached(f"page:v2:{cache_key}")
        if not cached_data:
            return jsonify({'status': 'success', 'data': None, 'url': None})

        # دعم الكاش القديم (نص عادي) والحديث (كائن يحوي url و referer)
        if isinstance(cached_data, dict):
            return jsonify({
                'status': 'success',
                'url': cached_data.get('url'),
                'referer': cached_data.get('referer'),
                'source': cached_data.get('source'),
                'data': cached_data
            })

        return jsonify({'status': 'success', 'url': cached_data, 'referer': None})

    elif request.method == 'POST':
        data = request.get_json(silent=True) or {}
        cache_key = data.get('key')
        target_url = data.get('url')
        referer = data.get('referer')
        source = data.get('source', 'generic')

        if cache_key and target_url:
            payload = {
                'url': target_url,
                'referer': referer,
                'source': source,
                'cached_at': int(time.time())
            }
            # حفظ الرابط مع الترويسات لمدة 48 ساعة
            set_cached(f"page:v2:{cache_key}", payload, ttl=48 * 3600)
            return jsonify({'status': 'success', 'message': 'Stream payload cached successfully'})

        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
