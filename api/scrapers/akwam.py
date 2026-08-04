import re
from urllib.parse import quote, urlparse
from bs4 import BeautifulSoup
import requests

TMDB_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}


def safe_url(url):
  """تحويل وتشفير الروابط التي تحتوي على حروف عربية إلى ترميز ASCII آمن."""
  if not url:
    return url
  return quote(url, safe=':/?&=#%')


def get_active_akwam_domain():
  """الاكتشاف الديناميكي لنطاق موقع أكوام النشط حالياً عبر ak.sv."""
  try:
    res = requests.get(
        'https://ak.sv/',
        headers=TMDB_HEADERS,
        timeout=6,
        allow_redirects=True,
    )
    parsed = urlparse(res.url)
    return f'{parsed.scheme}://{parsed.netloc}'
  except Exception as e:
    print(f'⚠️ Error resolving Akwam active domain: {e}')
    return 'https://akwam.it'


AKWAM_BASE_DOMAIN = get_active_akwam_domain()


def get_akwam_headers(referer_url=None):
  """توليد الهيدرز المطلوبة لكشط موقع أكوام مع ضبط الـ Referer المناسب."""
  ref = safe_url(referer_url) if referer_url else f'{AKWAM_BASE_DOMAIN}/'
  return {
      'User-Agent': TMDB_HEADERS['User-Agent'],
      'Referer': ref,
  }


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


def fetch_akwam_stream(title, orig_title, media_type):
  """كشط روابط البث المباشرة من موقع أكوام (.mp4)."""
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
        break

    if not card or not card.get('href'):
      return None

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
      return None

    watch_url = watch_btn['href']
    if not watch_url.startswith('http'):
      watch_url = f"{AKWAM_BASE_DOMAIN}/{watch_url.lstrip('/')}"

    watch_url = safe_url(watch_url)
    res_w = requests.get(
        watch_url, headers=get_akwam_headers(watch_url), timeout=8
    )

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

    return qualities if qualities else None

  except Exception as e:
    print(f'⚠️ Akwam Scraper Exception: {e}')
    return None
