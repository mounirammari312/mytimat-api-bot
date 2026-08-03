import json
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://mycima.pink"

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like'
        ' Gecko) Chrome/137.0.0.0 Mobile Safari/537.36'
    ),
    'Referer': f'{BASE_URL}/',
    'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8',
}

session = requests.Session()
session.headers.update(HEADERS)


def is_junk_image(url):
  if not url:
    return True
  url_l = url.lower()
  junk = ['favicon', 'logo', 'icon', 'banner', 'netflix', 'ui', 'theme']
  return any(k in url_l for k in junk)


def get_robust_metadata(soup):
  og_title = soup.find('meta', property='og:title')
  title = (
      ' '.join(og_title['content'].split()) if og_title else 'عنوان غير معروف'
  )

  poster = None
  og_image = soup.find('meta', property='og:image')
  if og_image and og_image.get('content'):
    candidate = og_image['content']
    if not is_junk_image(candidate):
      poster = candidate

  if not poster:
    poster_box = soup.select_one(
        '.we-poster, .Poster--Single, div.Poster, .PosterList'
    )
    if poster_box:
      img = poster_box.find('img')
      if img:
        src = (
            img.get('data-src')
            or img.get('data-lazy-src')
            or img.get('src')
            or ''
        )
        if not is_junk_image(src):
          poster = src

  story = None
  story_box = soup.select_one(
      '.Story--Single, .PostStory, .StoryMovie, .we-story'
  )
  if story_box and len(story_box.text.strip()) > 10:
    story = ' '.join(story_box.text.strip().split())

  if not story:
    og_desc = soup.find('meta', property='og:description') or soup.find(
        'meta', attrs={'name': 'description'}
    )
    if og_desc and og_desc.get('content'):
      story = ' '.join(og_desc['content'].split())

  return title, poster, story


def parse_servers(soup):
  servers_raw = soup.select('ul.WatchServersList li btn') or soup.select(
      '[data-watch]'
  )
  servers = []
  for idx, btn in enumerate(servers_raw, 1):
    name = btn.text.strip() or f'سيرفر {idx}'
    url = btn.get('data-watch') or btn.get('data-url')
    if url:
      servers.append({'id': idx, 'name': name, 'url': url})
  return servers


def parse_movie(movie_url):
  try:
    res = session.get(movie_url, timeout=10)
    if res.status_code != 200:
      return None

    soup = BeautifulSoup(res.text, 'html.parser')
    title, poster, story = get_robust_metadata(soup)
    servers = parse_servers(soup)

    return {
        'type': 'movie',
        'title': title,
        'url': movie_url,
        'poster': poster or '',
        'story': story or '',
        'servers_count': len(servers),
        'servers': servers,
    }
  except Exception as e:
    print(f'Error parsing movie {movie_url}: {e}')
    return None


def parse_series(series_url):
  try:
    res = session.get(series_url, timeout=10)
    if res.status_code != 200:
      return None

    soup = BeautifulSoup(res.text, 'html.parser')
    title, poster, story = get_robust_metadata(soup)

    ep_elements = soup.select('.EpisodesList a') or soup.select(
        'a[href*="/episode/"]'
    )
    episodes = []

    if (not poster or not story) and ep_elements:
      first_ep_url = ep_elements[0].get('href')
      if first_ep_url:
        res_ep1 = session.get(first_ep_url, timeout=10)
        soup_ep1 = BeautifulSoup(res_ep1.text, 'html.parser')
        _, ep_poster, ep_story = get_robust_metadata(soup_ep1)
        if not poster and ep_poster:
          poster = ep_poster
        if not story and ep_story:
          story = ep_story

    for ep in ep_elements:
      ep_title = ep.text.strip() or 'حلقة'
      ep_url = ep.get('href')
      if ep_url:
        episodes.append({'title': ep_title, 'url': ep_url})

    return {
        'type': 'series',
        'title': title,
        'url': series_url,
        'poster': poster or '',
        'story': story or '',
        'episodes_count': len(episodes),
        'episodes': episodes,
    }
  except Exception as e:
    print(f'Error parsing series {series_url}: {e}')
    return None


def main():
  database = {'movies': [], 'series': []}

  try:
    res_movies = session.get(f'{BASE_URL}/movies/', timeout=10)
    soup_movies = BeautifulSoup(res_movies.text, 'html.parser')
    for a in soup_movies.select('.GridItem a')[:10]:
      m_data = parse_movie(a.get('href'))
      if m_data:
        database['movies'].append(m_data)

    res_series = session.get(f'{BASE_URL}/series/', timeout=10)
    soup_series = BeautifulSoup(res_series.text, 'html.parser')
    for a in soup_series.select('.GridItem a')[:10]:
      s_data = parse_series(a.get('href'))
      if s_data:
        database['series'].append(s_data)

    with open('mycima_master_db.json', 'w', encoding='utf-8') as f:
      json.dump(database, f, ensure_ascii=False, indent=2)

    print('Successfully updated mycima_master_db.json')
  except Exception as e:
    print(f'Main execution error: {e}')


if __name__ == '__main__':
  main()
