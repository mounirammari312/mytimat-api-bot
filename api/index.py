from urllib.parse import quote, unquote, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
import requests
import re

# ==============================================================================
# ًں› ï¸ڈ ط¥ط¹ط¯ط§ط¯ط§طھ ط§ظ„طھط·ط¨ظٹظ‚ ظˆط§ظ„ط³ظٹط±ظپط± ط§ظ„ط±ط¦ظٹط³ظٹ (Vercel Entrypoint)
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
# 1. ط§ظƒطھط´ط§ظپ ط¯ظˆظ…ظٹظ† ط£ظƒظˆط§ظ… ط§ظ„ظ†ط´ط· طھظ„ظ‚ط§ط¦ظٹط§ظ‹
# ==============================================================================


def safe_url(url):
    return quote(url, safe=':/?&=#%') if url else url


def get_active_akwam_domain():
    """ط¬ظ„ط¨ ط§ظ„ظ†ط·ط§ظ‚ ط§ظ„ظ†ط´ط· ظ„ظ…ظˆظ‚ط¹ ط£ظƒظˆط§ظ… طھظ„ظ‚ط§ط¦ظٹط§ظ‹ ط¹ط¨ط± ط±ط§ط¨ط· ط§ظ„طھظˆط¬ظٹظ‡ ak.sv"""
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
# 2. ط¯ظˆط§ظ„ طھظ†ط³ظٹظ‚ ط¨ط·ط§ظ‚ط§طھ ط£ظƒظˆط§ظ… ظˆ TMDB
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

        title = 'ط؛ظٹط± ظ…طھظˆظپط±'
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
# 3. ظ…ط³ط§ط±ط§طھ ط§ظ„ظ€ API ط§ظ„ظƒظ„ظٹط© ظˆط§ظ„ظƒط§ظ…ظ„ط© (All Required Routes)
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
        'version': '6.3.0',
    })


@app.route('/api/config', methods=['GET'])
def get_config():
    """طھط²ظˆظٹط¯ ط§ظ„طھط·ط¨ظٹظ‚ ط¨ط¬ظ…ظٹط¹ ط§ظ„ظ…ظˆط§ظ‚ط¹ ظˆظ‚ظˆط§ط¹ط¯ ط§ظ„ظƒط´ط· ط§ظ„ط¯ظٹظ†ط§ظ…ظٹظƒظٹط© ظ„طھط­ط¯ظٹط« GenericScraper.

    ظ…ظ„ط§ط­ط¸ط© ظ‡ط§ظ…ط©: ط§ظ„ظ…ط­ط¯ط¯ط§طھ (selectors) ظٹط¬ط¨ ط£ظ† طھط³طھط®ط¯ظ… طµظٹط؛ط© CSS ط§ظ„ظ‚ظٹط§ط³ظٹط© ظ…ط«ظ„
    'a[href*=/movie/]' â€” ظ„ط§ طھط³طھط®ط¯ظ… ط§ط®طھطµط§ط±ط§طھ ط£ظˆ ط¥ط²ط§ظ„ط© ط§ظ„ط£ظ‚ظˆط§ط³.
    """
    return jsonify({
        'status': 'success',
        'version': '6.3.0',
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
                    'a[href*="/watch/"], a[href*="/series/"], article.post a'
                ),
                'watch_selector': 'iframe, [data-link], [data-url], [data-post]',
                'iframe_selector': 'iframe, iframe[data-src]',
                'link_regex': r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
                'requires_unpack': True,
                'ajax_required': True,
            },
        ],
    })


@app.route('/api/home', methods=['GET'])
def get_home():
    """ط¬ظ„ط¨ ط§ظ„ظ‚ظˆط§ط¦ظ… ط§ظ„ط±ط¦ظٹط³ظٹط© ظ„ظ„ط£ظپظ„ط§ظ… ظˆط§ظ„ظ…ط³ظ„ط³ظ„ط§طھ"""
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
            print(f'âڑ ï¸ڈ TMDB Fetch Exception: {tmdb_err}')

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
                    'title': 'ًں”¥ ط§ظ„ط£ظپظ„ط§ظ… ط§ظ„ط£ظƒط«ط± ط´ظ‡ط±ط©',
                    'has_see_all': True,
                    'see_all_params': {'type': 'movies', 'page': 1},
                    'items': trending_movies,
                },
                {
                    'key': 'trending_tv',
                    'title': 'ًں“؛ ط§ظ„ظ…ط³ظ„ط³ظ„ط§طھ ط§ظ„ط£ظƒط«ط± ظ…ط´ط§ظ‡ط¯ط©',
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
    """ط¬ظ„ط¨ ظ‚ط§ط¦ظ…ط© ط§ظ„ظƒطھط§ظ„ظˆط¬ ظˆطھطµظپط­ ط§ظ„ط£ظ‚ط³ط§ظ… ظˆط§ظ„طµظپط­ط§طھ"""
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
    """ط§ظ„ط¨ط­ط« ظپظٹ TMDB ط¨ط§ظ„ط£ط³ظ…ط§ط، ط§ظ„ط¹ط±ط¨ظٹط© ظˆط§ظ„ط¥ظ†ط¬ظ„ظٹط²ظٹط© ظ…ط¹ ط­ظ…ط§ظٹط© ظƒط§ظ…ظ„ط© ط¶ط¯ ط§ظ„ط§ظ†ظ‡ظٹط§ط±"""
    query = request.args.get('q', '')
    if not query:
        return jsonify({'status': 'error', 'message': 'Query missing'}), 400

    try:
        search_url = f'{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={quote(query)}&language=ar-SA'

        # ط±ظپط¹ ط§ظ„ظ…ظ‡ظ„ط© ط¥ظ„ظ‰ 8 ط«ظˆط§ظ†ظچ ظ„طھط¬ظ†ط¨ ط§ظ„ط§ظ†ظ‚ط·ط§ط¹ ظ…ط¹ ط§ظ„ط¥ظ†طھط±ظ†طھ ط§ظ„ط¶ط¹ظٹظپ
        res = requests.get(search_url, headers=TMDB_HEADERS, timeout=8)

        # ط¥ط°ط§ ظ„ظ… طھظƒظ† ط§ظ„ط§ط³طھط¬ط§ط¨ط© ظ†ط§ط¬ط­ط©طŒ ظ†ظڈط±ط¬ط¹ ظ‚ط§ط¦ظ…ط© ظپط§ط±ط؛ط© ط¨ط¯ظ„ط§ظ‹ ظ…ظ† ط§ظ†ظ‡ظٹط§ط± ط§ظ„طھط·ط¨ظٹظ‚
        if res.status_code != 200:
            return jsonify({'status': 'success', 'data': []})

        res_json = res.json()
        items = []

        for item in res_json.get('results', []):
            m_type = item.get('media_type')
            if m_type in ['movie', 'tv']:
                # ط­ظ…ط§ظٹط© طھظ‚ظٹظٹظ… ط§ظ„ظپظٹظ„ظ… ظ…ظ† ط§ظ„ظ‚ظٹظ… ط§ظ„ظپط§ط±ط؛ط© ظ„ظ…ظ†ط¹ ط£ط®ط·ط§ط، ط§ظ„ظ€ Type
                vote_avg = item.get('vote_average')
                rating = round(vote_avg, 1) if isinstance(vote_avg, (int, float)) else 0.0

                title = item.get('title') or item.get('name') or item.get('original_title') or 'ط¨ط¯ظˆظ† ط¹ظ†ظˆط§ظ†'
                orig_title = item.get('original_name') or item.get('original_title') or ''
                poster_path = item.get('poster_path')

                # طھط¬ظ‡ظٹط² ط§ظ„ط±ظˆط§ط¨ط· ظ„ظƒظ„ ط§ظ„ظ…ظˆط§ظ‚ط¹ ط§ظ„ظ…طھط§ط­ط© ظ„طھظپط§ط¯ظٹ ط§ظ„ط§ط±طھط¨ط§ط· ط¨ظ…ظˆظ‚ط¹ ظˆط§ط­ط¯ ظپظ‚ط·
                sources = {
                    'akwam': f"{AKWAM_BASE_DOMAIN}/search?q={quote(title)}",
                    'larroza': f"{LARROZA_BASE_DOMAIN}/search.php?keywords={quote(title)}",
                    'moviz-time': f"https://moviz-time.site/?s={quote(title)}"
                }

                items.append({
                    'id': str(item.get('id', '')),
                    'url': sources['akwam'],  # ط§ظ„ط±ط§ط¨ط· ط§ظ„ط§ظپطھط±ط§ط¶ظٹ ظ„ظ„طھظˆط§ظپظ‚ ظ…ط¹ ط§ظ„طھط·ط¨ظٹظ‚
                    'sources': sources,       # ط±ظˆط§ط¨ط· ط¥ط¶ط§ظپظٹط© ظ„ظƒظ„ ط§ظ„ظ…ظˆط§ظ‚ط¹
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
        print(f"âڑ ï¸ڈ Search Error: {e}")
        # ط§ظ„ط­ظ…ط§ظٹط© ط§ظ„ظ‚طµظˆظ‰: ط¥ط±ط¬ط§ط¹ ظ‚ط§ط¦ظ…ط© ظپط§ط±ط؛ط© ط¨ظƒظˆط¯ 200 ظ„ظ…ظ†ط¹ Force Close ظپظٹ طھط·ط¨ظٹظ‚ ط§ظ„ط£ظ†ط¯ط±ظˆظٹط¯
        return jsonify({'status': 'success', 'data': []})


# ==============================================================================
# 4. ظ…ط³ط§ط± طھظپط§طµظٹظ„ ط§ظ„ظ…ط³ظ„ط³ظ„ (Series Details)
# ==============================================================================


@app.route('/api/series-details', methods=['GET'])
def get_series_details():
    """ط¬ظ„ط¨ طھظپط§طµظٹظ„ ط§ظ„ظ…ط³ظ„ط³ظ„ ظˆط­ظ„ظ‚ط§طھ ط§ظ„ظ…ظˆط³ظ… ط§ظ„ظ…ط­ط¯ط¯ ظ…ط¹ ط§ظ„ظ…ط¹ط§ظ„ط¬ط© ط§ظ„ظ‡ط¬ظٹظ†ط© ظ„ظ…ظ†ط¹ ط£ط®ط·ط§ط، 404"""
    series_url = request.args.get('url', '').strip()
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()
    orig_title = request.args.get('original_title', '').strip()
    selected_season = request.args.get('season', '1').strip()

    # ط§ط³طھط®ط±ط§ط¬ ظ…ط¹ط±ظپ TMDB ط³ظˆط§ط، طھظ… طھظ…ط±ظٹط±ظ‡ ظپظٹ id ط£ظˆ url
    clean_tmdb_id = None
    if tmdb_id and tmdb_id.isdigit():
        clean_tmdb_id = tmdb_id
    elif series_url and series_url.isdigit():
        clean_tmdb_id = series_url

    # 1ï¸ڈâƒ£ ط§ظ„ظ…ط­ط§ظˆظ„ط© ط§ظ„ط£ظˆظ„ظ‰: ط¥ط°ط§ ظƒط§ظ† ظ„ط¯ظٹظ†ط§ ط±ط§ط¨ط· ظ…ط¨ط§ط´ط± ظ„طµظپط­ط© ط§ظ„ظ…ط³ظ„ط³ظ„ ظپظٹ ط£ظƒظˆط§ظ… (ظٹط­طھظˆظٹ ط¹ظ„ظ‰ /series/)
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
                            {'title': s.get_text(strip=True) or 'ظ…ظˆط³ظ…', 'url': s_href}
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
            print(f'âڑ ï¸ڈ Akwam Direct Series Error: {e}')

    # 2ï¸ڈâƒ£ ط§ظ„ظ…ط­ط§ظˆظ„ط© ط§ظ„ط«ط§ظ†ظٹط©: ط¥ط°ط§ ظƒط§ظ† ط§ظ„ط±ط§ط¨ط· ط±ط§ط¨ط· ط¨ط­ط«طŒ ظٹطھظ… ط§ط³طھط®ط±ط§ط¬ ط§ظ„ط§ط³ظ… ظˆط§ظ„ط¨ط­ط« ط¹ظ† طµظپط­ط© ط§ظ„ظ…ط³ظ„ط³ظ„ ظپظٹ ط£ظƒظˆط§ظ…
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
                                {'title': s.get_text(strip=True) or 'ظ…ظˆط³ظ…', 'url': s_href}
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
            print(f'âڑ ï¸ڈ Akwam Search Resolution Error: {e}')

    # 3ï¸ڈâƒ£ ط§ظ„ظ…ط­ط§ظˆظ„ط© ط§ظ„ط«ط§ظ„ط«ط©: ط¬ظ„ط¨ ط§ظ„ظ…ظˆط§ط³ظ… ظˆط§ظ„ط­ظ„ظ‚ط§طھ ط±ط³ظ…ظٹط§ظ‹ ظ…ظ† TMDB API
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
                        'title': s.get('name') or f'ط§ظ„ظ…ظˆط³ظ… {s_num}',
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
                    'title': f"ط§ظ„ط­ظ„ظ‚ط© {ep_num} - {ep.get('name', '')}",
                    'search_title': (
                        f'{title} ط§ظ„ظ…ظˆط³ظ… {season_num} ط§ظ„ط­ظ„ظ‚ط© {ep_num}'
                        if title
                        else f'ط§ظ„ظ…ظˆط³ظ… {season_num} ط§ظ„ط­ظ„ظ‚ط© {ep_num}'
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
            print(f'âڑ ï¸ڈ TMDB Series Season Switch Error: {tmdb_err}')

    # 4ï¸ڈâƒ£ ط§ظ„ط§ط³طھط¬ط§ط¨ط© ط§ظ„ط§ط­طھظٹط§ط·ظٹط© ط§ظ„ظ…ط¶ظ…ظˆظ†ط© ط¨ظ€ 200 OK ظ„طھظپط§ط¯ظٹ ط®ط·ط£ HTTP 404 ظپظٹ ط§ظ„ط£ظ†ط¯ط±ظˆظٹط¯
    return jsonify({
        'status': 'success',
        'data': {'current_season': 1, 'seasons': [], 'episodes': []},
        'message': 'ظ„ظ… ظٹطھظ… ط§ظ„ط¹ط«ظˆط± ط¹ظ„ظ‰ ط­ظ„ظ‚ط§طھ ظ„ظ‡ط°ط§ ط§ظ„ظ…ط³ظ„ط³ظ„',
    })


# ==============================================================================
# 5. ظ…ط³ط§ط± ط§ط³طھط®ط±ط§ط¬ ط±ظˆط§ط¨ط· ط§ظ„ط¨ط« (Stream) â€” ط§ط­طھظٹط§ط·ظٹ ط³ط­ط§ط¨ظٹ ظ„ظ„طھط·ط¨ظٹظ‚
# ==============================================================================

# ظ†ظ…ط· ط§ط³طھط®ط±ط§ط¬ ط±ظˆط§ط¨ط· MP4 ظˆ M3U8 ظ…ظ† HTML
STREAM_REGEX = re.compile(
    r'https?://[^\s"\'<>]+\.(?:mp4|m3u8|txt)[^\s"\'<>]*',
    re.IGNORECASE,
)


def _scrape_akwam_streams(title, original_title, is_tv):
    """ظƒط´ط· ط±ظˆط§ط¨ط· ط§ظ„ط¨ط« ظ…ظ† ظ…ظˆظ‚ط¹ ط£ظƒظˆط§ظ… ظƒط§ط­طھظٹط§ط·ظٹ ط³ط­ط§ط¨ظٹ."""
    search_term = original_title or title
    if not search_term:
        return []

    try:
        search_url = f'{AKWAM_BASE_DOMAIN}/search?q={quote(search_term)}'
        res = requests.get(search_url, headers=get_akwam_headers(), timeout=5)
        if res.status_code != 200:
            return []

        soup = BeautifulSoup(res.text, 'html.parser')
        # ط§ظ„ط¨ط­ط« ط¹ظ† ط¨ط·ط§ظ‚ط© ط§ظ„ظپظٹظ„ظ… ط£ظˆ ط§ظ„ظ…ط³ظ„ط³ظ„
        link_selector = 'a[href*="/series/"]' if is_tv else 'a[href*="/movie/"]'
        card = soup.select_one(link_selector)
        if not card:
            # ظ…ط­ط§ظˆظ„ط© ط¨ط£ظٹ ط¨ط·ط§ظ‚ط© ظپظٹظ„ظ…/ظ…ط³ظ„ط³ظ„
            card = soup.select_one('a[href*="/movie/"], a[href*="/series/"]')
        if not card or not card.get('href'):
            return []

        item_url = card['href']
        if not item_url.startswith('http'):
            item_url = f"{AKWAM_BASE_DOMAIN}/{item_url.lstrip('/')}"

        # ظ„ظ„ظ…ط³ظ„ط³ظ„ط§طھ: ظ†ط¨ط­ط« ط¹ظ† ط£ظˆظ„ ط­ظ„ظ‚ط©
        if is_tv:
            res_item = requests.get(
                safe_url(item_url), headers=get_akwam_headers(item_url), timeout=5
            )
            if res_item.status_code == 200:
                soup_item = BeautifulSoup(res_item.text, 'html.parser')
                ep_link = soup_item.select_one('a[href*="/episode/"]')
                if ep_link and ep_link.get('href'):
                    ep_url = ep_link['href']
                    if not ep_url.startswith('http'):
                        ep_url = f"{AKWAM_BASE_DOMAIN}/{ep_url.lstrip('/')}"
                    item_url = ep_url

        # ظپطھط­ طµظپط­ط© ط§ظ„ظ…ط´ط§ظ‡ط¯ط©
        res_item = requests.get(
            safe_url(item_url), headers=get_akwam_headers(item_url), timeout=5
        )
        if res_item.status_code != 200:
            return []

        soup_item = BeautifulSoup(res_item.text, 'html.parser')
        watch_link = soup_item.select_one('a[href*="/watch/"], a.link-btn')
        watch_url = item_url
        if watch_link and watch_link.get('href'):
            watch_url = watch_link['href']
            if not watch_url.startswith('http'):
                watch_url = f"{AKWAM_BASE_DOMAIN}/{watch_url.lstrip('/')}"

        res_watch = requests.get(
            safe_url(watch_url), headers=get_akwam_headers(watch_url), timeout=5
        )
        if res_watch.status_code != 200:
            return []

        # ط§ط³طھط®ط±ط§ط¬ ط±ظˆط§ط¨ط· MP4/M3U8 ظ…ظ† طµظپط­ط© ط§ظ„ظ…ط´ط§ظ‡ط¯ط©
        html = res_watch.text
        matches = STREAM_REGEX.findall(html)
        # طھظ†ظ‚ظٹط© ط§ظ„ط±ظˆط§ط¨ط· ظ…ظ† ط£ظƒظˆط§ط¯ HTML
        seen = set()
        streams = []
        for raw in matches:
            url = raw.replace('\\/', '/').replace('&amp;', '&').strip()
            url = url.rstrip('\\\'"),;]')
            if url in seen:
                continue
            # طھط¬ط§ظ‡ظ„ ط±ظˆط§ط¨ط· ط§ظ„ط¥ط¹ظ„ط§ظ†ط§طھ
            low = url.lower()
            if any(b in low for b in ['doubleclick', 'googlesyndication', 'facebook', 'twitter']):
                continue
            seen.add(url)

            # طھط­ط¯ظٹط¯ ط§ظ„ط¬ظˆط¯ط© ظ…ظ† ط§ظ„ط±ط§ط¨ط·
            quality = 'Auto'
            if '1080' in low:
                quality = '1080p FHD'
            elif '720' in low:
                quality = '720p HD'
            elif '480' in low:
                quality = '480p SD'
            elif '.m3u8' in low:
                quality = 'HLS'

            streams.append({
                'quality': quality,
                'url': url,
                'is_default': len(streams) == 0,
            })

        return streams
    except Exception as e:
        print(f'âڑ ï¸ڈ Akwam Stream Scrape Error: {e}')
        return []


@app.route('/api/stream', methods=['GET'])
def get_stream():
    """ط§ط­طھظٹط§ط·ظٹ ط³ط­ط§ط¨ظٹ ظ„ط§ط³طھط®ط±ط§ط¬ ط±ظˆط§ط¨ط· ط§ظ„ط¨ط« ظ…ظ† ط£ظƒظˆط§ظ… ط¹ظ†ط¯ظ…ط§ ظٹظپط´ظ„ ط§ظ„ظƒط´ط· ط§ظ„ظ…ط­ظ„ظٹ ظپظٹ ط§ظ„طھط·ط¨ظٹظ‚.

    ط§ظ„طھط·ط¨ظٹظ‚ ظٹط¹طھظ…ط¯ ط£ظˆظ„ط§ظ‹ ط¹ظ„ظ‰ GenericScraper ظ…ط­ظ„ظٹط§ظ‹طŒ ظˆظ‡ط°ط§ ط§ظ„ظ…ط³ط§ط± ظٹظڈط³طھط®ط¯ظ… ظپظ‚ط·
    ظƒط§ط­طھظٹط§ط·ظٹ ط¹ظ†ط¯ ظپط´ظ„ ط§ظ„ظƒط´ط· ط§ظ„ظ…ط­ظ„ظٹ (ظ…ط«ظ„ط§ظ‹ ط¨ط³ط¨ط¨ طھط؛ظٹط± DOM ظپظٹ ط£ظƒظˆط§ظ…).
    """
    title = request.args.get('title', '').strip()
    stream_type = request.args.get('type', 'movie').lower().strip()

    if not title:
        return jsonify({
            'status': 'success',
            'data': {'streams': [], 'title': '', 'type': stream_type},
        })

    is_tv = stream_type in ('tv', 'series')
    streams = _scrape_akwam_streams(title, title, is_tv)

    # ظ…ط­ط§ظˆظ„ط© ط«ط§ظ†ظٹط© ط¨ط§ظ„ط¹ظ†ظˆط§ظ† ط§ظ„ط£طµظ„ظٹ ط¥ط°ط§ ظپط´ظ„طھ ط§ظ„ط£ظˆظ„ظ‰ (ظ„ظ„ط£ظپظ„ط§ظ… ط§ظ„ط£ط¬ظ†ط¨ظٹط©)
    if not streams:
        try:
            # ط§ظ„ط¨ط­ط« ظپظٹ TMDB ط¹ظ† ط§ظ„ط¹ظ†ظˆط§ظ† ط§ظ„ط£طµظ„ظٹ
            tmdb_search = f'{TMDB_BASE_URL}/search/multi?api_key={TMDB_API_KEY}&query={quote(title)}&language=en-US'
            res = requests.get(tmdb_search, headers=TMDB_HEADERS, timeout=4)
            if res.status_code == 200:
                for item in res.json().get('results', []):
                    if item.get('media_type') in ('movie', 'tv'):
                        orig = item.get('original_title') or item.get('original_name')
                        if orig and orig.lower() != title.lower():
                            streams = _scrape_akwam_streams(orig, orig, is_tv)
                            if streams:
                                break
        except Exception as e:
            print(f'âڑ ï¸ڈ TMDB Original Title Fallback Error: {e}')

    return jsonify({
        'status': 'success',
        'data': {
            'streams': streams,
            'title': title,
            'type': stream_type,
            'active_domain': AKWAM_BASE_DOMAIN,
        },
    })


# ==============================================================================
# 6. ظ…ط³ط§ط± طھظپط§طµظٹظ„ ط§ظ„ظپظٹظ„ظ… (Movie Details) â€” ظٹط¹طھظ…ط¯ ط¹ظ„ظ‰ TMDB
# ==============================================================================


@app.route('/api/movie-details', methods=['GET'])
def get_movie_details():
    """ط¬ظ„ط¨ طھظپط§طµظٹظ„ ط§ظ„ظپظٹظ„ظ… ظ…ظ† TMDB (ط§ظ„ظˆطµظپطŒ ط§ظ„ط·ط§ظ‚ظ…طŒ ط§ظ„ظپظٹط¯ظٹظˆظ‡ط§طھ).

    ظٹظڈط³طھط®ط¯ظ… ط¹ظ†ط¯ ط§ظ„ط­ط§ط¬ط© ظ„ط¹ط±ط¶ ظ…ط¹ظ„ظˆظ…ط§طھ ط¥ط¶ط§ظپظٹط© ظپظٹ ط´ط§ط´ط© ط§ظ„طھظپط§طµظٹظ„.
    """
    tmdb_id = request.args.get('id', '').strip()
    title = request.args.get('title', '').strip()

    clean_id = None
    if tmdb_id and tmdb_id.isdigit():
        clean_id = tmdb_id
    elif title:
        # ط§ظ„ط¨ط­ط« ط¹ظ† TMDB ID ط¨ط§ظ„ط¹ظ†ظˆط§ظ†
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
        return jsonify({
            'status': 'success',
            'data': None,
            'message': 'ظ„ظ… ظٹطھظ… ط§ظ„ط¹ط«ظˆط± ط¹ظ„ظ‰ طھظپط§طµظٹظ„',
        })

    try:
        detail_url = f'{TMDB_BASE_URL}/movie/{clean_id}?api_key={TMDB_API_KEY}&language=ar-SA&append_to_response=credits,videos'
        res = requests.get(detail_url, headers=TMDB_HEADERS, timeout=5)
        if res.status_code != 200:
            return jsonify({'status': 'success', 'data': None})

        data = res.json()
        return jsonify({
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
            },
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
