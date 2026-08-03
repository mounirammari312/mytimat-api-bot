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
  """توحيد النصوص العربية لمنع تكرار الهمزات والأحرف"""
  text = re.sub(r'[أإآ]', 'ا', text)
  text = re.sub(r'ة', 'ه', text)
  return text.strip().lower()


def clean_series_title(raw_title):
  """تنقية عنوان العمل واستخراج اسمه الأساسي"""
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


def discover_category_urls():
  """استخراج روابط الأقسام الحقيقية مباشرة من قائمة الموقع الرئيسية"""
  category_urls = {}
  try:
    res = requests.get(BASE_URL, headers=HEADERS, timeout=8)
    soup = BeautifulSoup(res.text, 'html.parser')

    KEYWORDS = {
        'foreign_movies': ('افلام اجنبي', 'movies', '🎬 أفلام أجنبية'),
        'foreign_series': ('مسلسلات اجنبي', 'series', '📺 مسلسلات أجنبية'),
        'turkish_series': ('مسلسلات تركي', 'series', '🇹🇷 مسلسلات تركية'),
        'arabic_movies': ('افلام عربي', 'movies', '🔥 أفلام عربية'),
        'arabic_series': ('مسلسلات عربي', 'series', '🌙 مسلسلات عربية'),
    }

    for a in soup.find_all('a', href=True):
      text = normalize_text(a.get_text(strip=True))
      href = a['href']

      for cat_key, (kw, ctype, display_name) in KEYWORDS.items():
        if cat_key not in category_urls and kw in text:
          full_url = (
              href
              if href.startswith('http')
              else f"{BASE_URL}/{href.lstrip('/')}"
          )
          category_urls[cat_key] = {
              'title': display_name,
              'url': full_url,
              'type': ctype,
          }
  except Exception:
    pass

  return category_urls


def fetch_perfect_category_items(base_url, content_type, limit=10):
  """جلب عناصر نظيفة وفريدة مع البوسترات عبر التصفح المتتابع"""
  items = []
  seen_base_titles = set()

  for page in range(1, 4):
    if len(items) >= limit:
      break
    page_url = base_url if page == 1 else f'{base_url}&page={page}'

    try:
      res = requests.get(page_url, headers=HEADERS, timeout=8)
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

        # 1. الفلترة الصارمة لنوع المحتوى
        if content_type == 'series' and 'فيلم' in norm_raw:
          continue
        if content_type == 'movies' and (
            'مسلسل' in norm_raw or 'حلقة' in norm_raw
        ):
          continue

        # 2. تنقية العنوان والتجميع
        base_title = clean_series_title(raw_title)
        norm_base = normalize_text(base_title)

        if norm_base in seen_base_titles:
          continue

        # 3. استخراج البوستر
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


# 1️⃣ الواجهة الرئيسية الشاملة لجميع أقسام الموقع (/api/home)
@app.route('/api/home', methods=['GET'])
def get_home():
  try:
    res = requests.get(BASE_URL, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')

    sections = []
    seen_urls = set()

    # قراءة كل قسم موجود في قائمة الموقع العلوي وتحويله لصف في الشاشة الرئيسية
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

          c_type = (
              'series'
              if ('مسلسل' in title or 'series' in href.lower())
              else 'movies'
          )
          cat_slug = href.split('cat=')[-1] if 'cat=' in href else 'all'

          # جلب 8 أعمال فريدة وممتازة لهذا القسم
          items = fetch_perfect_category_items(
              full_url, content_type=c_type, limit=8
          )

          if items:
            sections.append({
                'key': cat_slug,
                'title': title,
                'items': items,
            })

    return jsonify({'status': 'success', 'data': sections})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500










# 2️⃣ الكاتالوج الشامل المطور بدعم التصفح اللانهائي (Pagination)
@app.route('/api/catalog', methods=['GET'])
def get_catalog():
  page = int(request.args.get('page', '1'))
  cat_key = request.args.get('cat', 'movies').lower()
  limit = int(request.args.get('limit', '30'))  # رفع الحد الإفتراضي إلى 30

  discovered_cats = discover_category_urls()

  if cat_key in discovered_cats:
    cat_data = discovered_cats[cat_key]
    items = fetch_perfect_category_items(
        cat_data['url'], content_type=cat_data['type'], limit=limit, start_page=page
    )
  else:
    url = (
        f'{BASE_URL}/'
        if page == 1
        else f'{BASE_URL}/index.php?page={page}'
    )
    items = fetch_perfect_category_items(url, content_type='any', limit=limit, start_page=page)

  return jsonify({'status': 'success', 'page': page, 'cat': cat_key, 'data': items})








# 3️⃣ البحث المباشر (Search)
@app.route('/api/search', methods=['GET'])
def search():
  query = request.args.get('q', '')
  if not query:
    return jsonify({'status': 'error', 'message': 'Query missing'}), 400
  try:
    url = f'{BASE_URL}/search.php?keywords={query}'
    items = fetch_perfect_category_items(url, content_type='any', limit=30)
    return jsonify({'status': 'success', 'data': items})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 4️⃣ التفاصيل والحلقات المنقاة (Details & Episodes)
@app.route('/api/details', methods=['GET'])
def get_details():
  vid = request.args.get('vid', '')
  if not vid:
    return jsonify({'status': 'error', 'message': 'vid missing'}), 400
  try:
    res = requests.get(
        f'{BASE_URL}/play.php?vid={vid}', headers=HEADERS, timeout=10
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


# 5️⃣ اقتناص رابط البث المباشر (Multi-Server Stream Fetcher)
@app.route('/api/stream', methods=['GET'])
def get_stream():
  vid = request.args.get('vid', '')
  if not vid:
    return jsonify({'status': 'error', 'message': 'vid missing'}), 400

  play_url = f'{BASE_URL}/play.php?vid={vid}'
  try:
    res = requests.get(play_url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')

    servers = soup.select('li[id*="server"], li[data-embed]')

    def server_priority(s):
      sid = s.get('id', '').lower()
      if 'vidspeed' in sid or 'rty' in sid or 'vk' in sid or 'mp4' in sid:
        return 0
      return 1

    sorted_servers = sorted(servers, key=server_priority)

    for srv in sorted_servers:
      srv_id = srv.get('id', '').lower()
      if 'vidoba' in srv_id or 'filemoon' in srv_id or 'vidmoly' in srv_id:
        continue

      embed_attr = srv.get('data-embed', '')
      match = re.search(r'src=["\']([^"\']+)["\']', embed_attr)
      embed_url = match.group(1) if match else ''

      if not embed_url or not embed_url.startswith('http'):
        continue

      try:
        req_headers = {
            'User-Agent': HEADERS['User-Agent'],
            'Referer': embed_url,
        }
        srv_res = requests.get(
            embed_url,
            headers={
                'User-Agent': HEADERS['User-Agent'],
                'Referer': BASE_URL,
            },
            timeout=8,
        )
        html = srv_res.text

        if (
            'File is no longer available' in html
            or srv_res.status_code != 200
        ):
          continue

        if 'vk.com' in embed_url:
          vk_matches = re.findall(
              r'https?:\\/\\/[^\s"\'<>\\]+?\.(?:mp4|m3u8)[^\s"\'<>\\]*',
              html,
          )
          if vk_matches:
            clean_url = vk_matches[-1].replace('\\/', '/')
            return jsonify({
                'status': 'success',
                'data': {
                    'stream_url': clean_url,
                    'headers': {'User-Agent': HEADERS['User-Agent']},
                },
            })

        m3u8_matches = re.findall(
            r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', html
        )

        if not m3u8_matches and 'eval(function(p,a,c,k,e' in html:
          unpacked = unpack_js(html)
          m3u8_matches = re.findall(
              r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked
          )
          if not m3u8_matches:
            fm = re.search(
                r'file\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                unpacked,
            )
            if fm:
              m3u8_matches = [fm.group(1)]

        if m3u8_matches:
          stream_url = list(set(m3u8_matches))[0]
          return jsonify({
              'status': 'success',
              'data': {
                  'stream_url': stream_url,
                  'headers': req_headers,
              },
          })
      except Exception:
        continue

    return jsonify(
        {'status': 'error', 'message': 'Failed to extract stream link'}
    ), 404
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500


# 6️⃣ نقطة نهاية لجلب جميع أقسام وتصنيفات الموقع ديناميكياً
@app.route('/api/categories', methods=['GET'])
def get_all_categories():
  try:
    res = requests.get(BASE_URL, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')

    categories = []
    seen_urls = set()

    # البحث في كافة روابط القوائم
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

          # تحديد نوع المحتوى تلقائياً (فيلم أو مسلسل)
          c_type = (
              'series'
              if ('مسلسل' in title or 'series' in href.lower())
              else 'movies'
          )

          # استخراج معرّف التصنيف cat slug
          cat_slug = href.split('cat=')[-1] if 'cat=' in href else 'all'

          categories.append({
              'id': cat_slug,
              'title': title,
              'url': full_url,
              'type': c_type,
          })

    return jsonify({'status': 'success', 'data': categories})
  except Exception as e:
    return jsonify({'status': 'error', 'message': str(e)}), 500







if __name__ == '__main__':
  app.run(debug=True)

