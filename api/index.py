import html as html_module
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

app = Flask(__name__)

BASE_URL = "https://mycimatv.online"
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Referer': f'{BASE_URL}/',
}


def normalize_text(text):
  """توحيد النصوص العربية لمنع التكرار"""
  if not text:
    return ''
  text = re.sub(r'[أإآ]', 'ا', text)
  text = re.sub(r'ة', 'ه', text)
  return text.strip().lower()


def clean_series_title(raw_title):
  """تنقية عنوان العمل واستخراج اسمه الأساسي"""
  if not raw_title:
    return ''
  title = re.sub(
      r'(?:الحلقة|حلقة)\s*\d+.*', '', raw_title, flags=re.IGNORECASE
  )
  title = re.sub(
      r'(?:الموسم|موسم)\s*\d+.*', '', title, flags=re.IGNORECASE
  )
  title = re.sub(
      r'(?:مترجم|مترجمة|مدبلج|مدبلجة|ماي سيما|HD|اون لاين|كامل).*',
      '',
      title,
      flags=re.IGNORECASE,
  )
  title = re.sub(r'^مشاهدة\s+', '', title, flags=re.IGNORECASE)
  return title.strip()


def unpack_js(packed_code):
  """دالة فك تشفير كود Packed JS المخبأ"""
  try:
    pattern = (
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)"
    )
    match = re.search(pattern, packed_code, re.DOTALL)
    if not match:
      return ''

    payload, base_str, count_str, keywords_str = match.groups()
    base, count, keywords = (
        int(base_str),
        int(count_str),
        keywords_str.split('|'),
    )

    def encode_base(num, b):
      chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
      return (
          chars[num]
          if num < b
          else encode_base(num // b, b) + chars[num % b]
      )

    syms = {
        encode_base(i, base): (
            keywords[i]
            if i < len(keywords) and keywords[i]
            else encode_base(i, base)
        )
        for i in range(count)
    }
    return re.sub(
        r'\b\w+\b', lambda m: syms.get(m.group(0), m.group(0)), payload
    )
  except Exception:
    return ''


def extract_stream_from_embed(embed_url):
  """استخراج رابط البث المباشر المطور مع دعم التوكنات ومشغلات HLS/Clappr"""
  try:
    if embed_url.startswith('//'):
      embed_url = 'https:' + embed_url

    req_headers = {'User-Agent': HEADERS['User-Agent'], 'Referer': embed_url}
    res = requests.get(
        embed_url,
        headers={'User-Agent': HEADERS['User-Agent'], 'Referer': BASE_URL},
        timeout=8,
        allow_redirects=True,
    )
    html = res.text

    if 'File is no longer available' in html or res.status_code != 200:
      return None, None

    html_clean = html.replace('\\/', '/')

    # 1️⃣ البحث عن روابط m3u8 أو mp4 مع دعم معلمات التوكنات (?token=...)
    stream_matches = re.findall(
        r'(?:https?:)?//[^\s"\'<>\\]+?\.(?:m3u8|mp4)[^\s"\'<>\\]*', html_clean
    )

    # 2️⃣ فك تشفير Packed JS عند وجود كود eval
    if not stream_matches and 'eval(function(p,a,c,k,e' in html:
      unpacked = unpack_js(html)
      if unpacked:
        unpacked_clean = unpacked.replace('\\/', '/')
        stream_matches = re.findall(
            r'(?:https?:)?//[^\s"\'<>\\]+?\.(?:m3u8|mp4)[^\s"\'<>\\]*',
            unpacked_clean,
        )
        if not stream_matches:
          fm = re.search(
              r'(?:file|source|src)\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
              unpacked_clean,
          )
          if fm:
            stream_matches = [fm.group(1)]

    # 3️⃣ دعم أنماط الجافاسكريبت الحديثة (Clappr / HLS.js / JWPlayer)
    if not stream_matches:
      js_patterns = [
          (
              r'(?:file|source|src|loadSource)\s*[:\(]\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']'
          ),
          r'["\']((?:https?:)?//[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*)"',
      ]
      for pat in js_patterns:
        fm = re.findall(pat, html_clean)
        if fm:
          stream_matches.extend(fm)

    if stream_matches:
      clean_urls = []
      for url in stream_matches:
        if url.startswith('//'):
          url = 'https:' + url
        url = url.split('&amp;')[0]
        clean_urls.append(url)

      if clean_urls:
        return clean_urls[0], req_headers

  except Exception:
    pass

  return None, None


def fetch_category_items_fast(base_url, content_type='any', limit=15, page=1):
  """جلب العناصر السريع بدون تكرار الحلقات"""
  items = []
  seen_base_titles = set()
  page_url = base_url if page == 1 else f'{base_url}&page={page}'

  try:
    res = requests.get(page_url, headers=HEADERS, timeout=6)
    soup = BeautifulSoup(res.text, 'html.parser')

    for post in soup.select('.block-post, li:has(div.imgSer), a[href*="vid="]'):
      a_tag = post if post.name == 'a' else post.find('a', href=True)
      if not a_tag or 'vid=' not in a_tag.get('href', ''):
        continue

      vid = a_tag['href'].split('vid=')[-1]
      raw_title = a_tag.get('title', '').strip() or a_tag.get_text(strip=True)

      if not raw_title or len(raw_title) < 4 or 'صفحة' in raw_title:
        continue

      norm_raw = normalize_text(raw_title)

      if content_type == 'series' and 'فيلم' in norm_raw:
        continue
      if content_type == 'movies' and (
          'مسلسل' in norm_raw or 'حلقة' in norm_raw
      ):
        continue

      base_title = clean_series_title(raw_title)
      norm_base = normalize_text(base_title)

      if norm_base in seen_base_titles:
        continue

      poster = ''
      if post.name != 'a':
        img_ser = post.find('div', class_='imgSer')
        if img_ser and img_ser.get('style'):
          m = re.search(r"url\(['\"]?(.*?)['\"]?\)", img_ser['style'])
          if m:
            poster = m.group(1)

      if not poster and post.find('img'):
        img = post.find('img')
        poster = img.get('src') or img.get('data-src') or ''

      if poster and not poster.startswith('http'):
        poster = f"{BASE_URL}/{poster.lstrip('/')}"

      seen_base_titles.add(norm_base)
      items.append({'vid': vid, 'title': base_title, 'poster': poster})

      if len(items) >= limit:
        break
  except Exception:
    pass

  return items


# 1️⃣ الواجهة الرئيسية (/api/home)
@app.route('/api/home', methods=['GET'])
def get_home():
  try:
    MAIN_CATEGORIES = [
        (
            'foreign_movies',
            '🎬 أفلام أجنبية',
            f'{BASE_URL}/category.php?cat=aflam-ajnbe111',
            'movies',
        ),
        (
            'foreign_series',
            '📺 مسلسلات أجنبية',
            f'{BASE_URL}/category.php?cat=mslslat-ajnbe11',
            'series',
        ),
        (
            'turkish_series',
            '🇹🇷 مسلسلات تركية',
            f'{BASE_URL}/category.php?cat=mslslat-trke1',
            'series',
        ),
        (
            'arabic_movies',
            '🔥 أفلام عربية',
            f'{BASE_URL}/category.php?cat=aflam-a',
            'movies',
        ),
        (
            'arabic_series',
            '🌙 مسلسلات عربية',
            f'{BASE_URL}/category.php?cat=mslslat-arbe122',
            'series',
        ),
    ]

    sections = []
    for key, title, url, ctype in MAIN_CATEGORIES:
      items = fetch_category_items_fast(
          url, content_type=ctype, limit=10, page=1
      )
      if items:
        sections.append({'key': key, 'title': title, 'items': items})

    return jsonify({'status': 'success', 'data': sections})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 2️⃣ الكاتالوج والتصفح بالأقسام (/api/catalog)
@app.route('/api/catalog', methods=['GET'])
def get_catalog():
  page = int(request.args.get('page', '1'))
  cat_slug = request.args.get('cat', 'movies').lower()
  limit = int(request.args.get('limit', '20'))

  if cat_slug == 'series':
    url = f'{BASE_URL}/all-series.php'
    ctype = 'series'
  elif cat_slug == 'movies':
    url = f'{BASE_URL}/index.php'
    ctype = 'movies'
  else:
    url = f'{BASE_URL}/category.php?cat={cat_slug}'
    ctype = 'series' if 'mslsl' in cat_slug or 'series' in cat_slug else 'movies'

  items = fetch_category_items_fast(
      url, content_type=ctype, limit=limit, page=page
  )
  return jsonify(
      {'status': 'success', 'page': page, 'cat': cat_slug, 'data': items}
  )


# 3️⃣ نقطة نهاية الأقسام (/api/categories)
@app.route('/api/categories', methods=['GET'])
def get_all_categories():
  try:
    res = requests.get(BASE_URL, headers=HEADERS, timeout=6)
    soup = BeautifulSoup(res.text, 'html.parser')

    categories = []
    seen_urls = set()

    for a in soup.find_all('a', href=True):
      href = a['href']
      title = a.get_text(strip=True)

      if 'category.php' in href or 'all-series.php' in href:
        full_url = (
            href
            if href.startswith('http')
            else f"{BASE_URL}/{href.lstrip('/')}"
        )

        if (
            full_url not in seen_urls
            and title
            and len(title) > 2
            and 'الرئيسية' not in title
        ):
          seen_urls.add(full_url)
          cat_slug = href.split('cat=')[-1] if 'cat=' in href else 'series'
          ctype = (
              'series'
              if ('مسلسل' in title or 'mslsl' in cat_slug)
              else 'movies'
          )

          categories.append({
              'id': cat_slug,
              'title': title,
              'url': full_url,
              'type': ctype,
          })

    return jsonify({'status': 'success', 'data': categories})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 4️⃣ البحث المباشر (Search)
@app.route('/api/search', methods=['GET'])
def search():
  query = request.args.get('q', '')
  if not query:
    return jsonify({'status': 'error', 'message': 'Query missing'}), 400
  try:
    url = f'{BASE_URL}/search.php?keywords={query}'
    items = fetch_category_items_fast(
        url, content_type='any', limit=20, page=1
    )
    return jsonify({'status': 'success', 'data': items})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 5️⃣ التفاصيل والحلقات المنقاة (/api/details)
@app.route('/api/details', methods=['GET'])
def get_details():
  vid = request.args.get('vid', '')
  if not vid:
    return jsonify({'status': 'error', 'message': 'vid missing'}), 400
  try:
    res = requests.get(
        f'{BASE_URL}/play.php?vid={vid}', headers=HEADERS, timeout=8
    )
    soup = BeautifulSoup(res.text, 'html.parser')

    title_el = (
        soup.select_one('h1')
        or soup.select_one('.entry-title')
        or soup.select_one('title')
    )
    title = title_el.get_text(strip=True) if title_el else ''

    poster_el = soup.select_one('.poster img') or soup.select_one(
        'img[src*="uploads"]'
    )
    poster = (
        poster_el.get('src') or poster_el.get('data-src') if poster_el else ''
    )
    if poster and not poster.startswith('http'):
      poster = f"{BASE_URL}/{poster.lstrip('/')}"

    story_el = (
        soup.select_one('.story')
        or soup.select_one('.description')
        or soup.select_one('.entry-content')
    )
    story = story_el.get_text(strip=True) if story_el else ''

    episodes = []
    seen_vids = set()
    IGNORE_KEYWORDS = [
        'السابقة',
        'التالية',
        'الرئيسية',
        'صفحة',
        'فيس بوك',
        'تليجرام',
    ]

    for a in soup.find_all('a', href=True):
      href = a['href']
      ep_title = a.get_text(strip=True)

      if ('watch.php?vid=' in href or 'play.php?vid=' in href) and ep_title:
        ep_vid = href.split('vid=')[-1]
        if (
            ep_vid == vid
            or ep_vid in seen_vids
            or any(kw in ep_title for kw in IGNORE_KEYWORDS)
        ):
          continue

        seen_vids.add(ep_vid)
        episodes.append({'vid': ep_vid, 'title': ep_title})

    def get_episode_number(item):
      match = re.search(r'(?:الحلقة|حلقة)\s*(\d+)', item['title'])
      return int(match.group(1)) if match else 9999

    episodes.sort(key=get_episode_number)

    return jsonify({
        'status': 'success',
        'data': {
            'vid': vid,
            'title': title,
            'poster': poster,
            'story': story,
            'episodes': episodes,
        },
    })
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 6️⃣ اقتناص رابط البث الشامل والمعدل لجميع الأفلام والمسلسلات (/api/stream)
@app.route('/api/stream', methods=['GET'])
def get_stream():
  vid = request.args.get('vid', '')
  if not vid:
    return jsonify({'status': 'error', 'message': 'vid missing'}), 400

  play_url = f'{BASE_URL}/play.php?vid={vid}'
  try:
    res = requests.get(play_url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')

    targets = []

    # أ) جلب الـ iframe المباشر الموجود في أعلى الصفحة الرئيسية
    for iframe in soup.select('iframe[src], iframe[data-src]'):
      src = iframe.get('src') or iframe.get('data-src')
      if src and 'facebook' not in src and 'google' not in src:
        targets.append(src)

    # ب) جلب قائمة السيرفرات والأزرار
    servers = soup.select(
        'li[id*="server"], li[data-embed], .servers-list li, ul.servers li,'
        ' [data-url], [data-embed]'
    )
    for srv in servers:
      raw_embed = ''
      for attr in [
          'data-embed',
          'data-url',
          'data-src',
          'data-link',
          'href',
          'src',
      ]:
        val = srv.get(attr, '')
        if val:
          raw_embed = val
          break

      if not raw_embed:
        iframe = srv.find('iframe')
        if iframe and iframe.get('src'):
          raw_embed = iframe.get('src')

      if raw_embed:
        raw_embed = html_module.unescape(raw_embed)
        match_src = re.search(
            r'(?:src|href)=["\']([^"\']+)["\']', raw_embed, re.IGNORECASE
        )
        embed_url = (
            match_src.group(1)
            if match_src
            else (
                re.search(r'(?:https?:)?//[^\s"\'<>]+', raw_embed).group(0)
                if re.search(r'(?:https?:)?//[^\s"\'<>]+', raw_embed)
                else ''
            )
        )
        if embed_url:
          targets.append(embed_url)

    # فحص الأهداف وتمريرها لاستخراج الرابط
    for embed_url in targets:
      if not embed_url or (
          not embed_url.startswith('http') and not embed_url.startswith('//')
      ):
        continue

      embed_url = embed_url.rstrip('"\'>;')
      stream_url, req_headers = extract_stream_from_embed(embed_url)

      if stream_url:
        return jsonify({
            'status': 'success',
            'data': {
                'stream_url': stream_url,
                'headers': req_headers,
            },
        })

    return jsonify(
        {'status': 'error', 'message': 'Failed to extract stream link'}
    ), 404
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
  app.run(debug=True)

