import re

DIGITS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def base_encode(num, base):
  """تحويل الأرقام إلى قواعد نصية لفك تشفير Dean Edwards."""
  if num == 0:
    return DIGITS[0]
  res = []
  while num > 0:
    res.append(DIGITS[num % base])
    num //= base
  return ''.join(reversed(res))


def unpack_dean_edwards(script_text):
  """فك تشفير أكواد eval(function(p,a,c,k,e,d)...) لسيرفرات okhd و Vidmoly وغيرها من سيرفرات البث."""
  pattern = r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\s*\(\s*'(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
  match = re.search(pattern, script_text, re.DOTALL)
  if not match:
    return script_text

  p, a_str, c_str, k_str = match.groups()
  a, c = int(a_str), int(c_str)
  k = k_str.split('|')

  for i in range(c - 1, -1, -1):
    symbol = base_encode(i, a)
    if i < len(k) and k[i]:
      p = re.sub(r'\b' + re.escape(symbol) + r'\b', k[i], p)
  return p
