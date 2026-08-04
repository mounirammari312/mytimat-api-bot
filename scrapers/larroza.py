import json
import re
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
import requests

# استدعاء دالة تفكيك التشفير من المحرك المركزي core
from core.unpacker import unpack_dean_edwards

LARROZA_BASE_DOMAIN = 'https://larroza.mom'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Referer': f'{LARROZA_BASE_DOMAIN}/',
}


def fetch_larroza_stream(title, orig_title, host_url):
  """كشط موقع لاروزا اعتماداً على السلسلة المضمونة التي اختبرناها:

  Search (keywords) -> video.php -> embed.php -> iframe (okhd) -> Unpack ->
  .m3u8 Proxy
  """
  search_queries = [q for q in [title, orig_title] if q]

  for query in search_queries:
    try:
      # 1. البحث باستخدام keywords
      search_url = f'{LARROZA_BASE_DOMAIN}/search.php?keywords={quote(query)}'
      res_search = requests.get(search_url, headers=HEADERS, timeout=8)
      soup_search = BeautifulSoup(res_search.text, 'html.parser')

      video_links = [
          a['href']
          for a in soup_search.find_all('a', href=True)
          if 'video.php' in a['href']
      ]

      if not video_links:
        continue

      target_video = video_links[0]

      # 2. التحويل التلقائي لصفحة المشغّل embed.php
      embed_page_url = target_video.replace('video.php', 'embed.php')
      if not embed_page_url.startswith('http'):
        embed_page_url = urljoin(LARROZA_BASE_DOMAIN, embed_page_url)

      # 3. فتح embed.php واقتناص سيرفر okhd
      res_embed = requests.get(embed_page_url, headers=HEADERS, timeout=8)
      soup_embed = BeautifulSoup(res_embed.text, 'html.parser')

      iframes = soup_embed.find_all('iframe')
      if not iframes:
        continue

      okhd_embed_url = iframes[0].get('src')
      if not okhd_embed_url.startswith('http'):
        okhd_embed_url = urljoin(embed_page_url, okhd_embed_url)

      # 4. فتح سيرفر okhd وتفكيك تشفير Dean Edwards
      emb_headers = {
          'User-Agent': HEADERS['User-Agent'],
          'Referer': 'https://larroza.mom/',
      }
      res_okhd = requests.get(okhd_embed_url, headers=emb_headers, timeout=8)

      unpacked = unpack_dean_edwards(res_okhd.text)
      m3u8_matches = re.findall(
          r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*', unpacked
      )

      if m3u8_matches:
        raw_stream = m3u8_matches[0]
        h_json = json.dumps(
            {'User-Agent': HEADERS['User-Agent'], 'Referer': okhd_embed_url}
        )
        proxy_url = f'{host_url}hls-proxy?url={quote(raw_stream)}&headers={quote(h_json)}'

        return [{
            'quality': 'سيرفر لاروزا (HLS بروكسي)',
            'url': proxy_url,
            'is_default': True,
        }]
    except Exception as e:
      print(f'⚠️ Larroza Scraper Exception for query {query}: {e}')
      continue

  return None
