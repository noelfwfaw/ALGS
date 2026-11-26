"""Sync static Resonance Solstice trade data from resonance-columba.com.

Usage:
    toolkit/python.exe dev_tools/update_resonance_columba_data.py
"""

import json
import os
import re
import sys
import urllib.request

import requests

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

COLUMBA_BASE_URL = 'https://www.resonance-columba.com'
OUTPUT_PATH = os.path.join(ROOT, 'module', 'resonance', 'columba_data.json')
TARGET_EXPORTS = (
    'CITIES',
    'CITY_ATTACH_LIST',
    'CITY_FATIGUES',
    'CITY_WITH_PRESTIGE',
    'PRODUCTS',
    'RESONANCE_SKILLS',
)


def _normalized_proxies():
    proxies = {}
    for scheme, proxy_url in urllib.request.getproxies().items():
        if proxy_url.startswith('https://127.0.0.1') or proxy_url.startswith('https://localhost'):
            proxies[scheme] = 'http://' + proxy_url[len('https://'):]
        else:
            proxies[scheme] = proxy_url
    return proxies


def http_get_text(url, timeout=15):
    """Fetch text via direct connection first, falling back to normalized system proxies."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    direct = requests.Session()
    direct.trust_env = False
    try:
        resp = direct.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        proxies = _normalized_proxies()
        if not proxies:
            raise
        proxied = requests.Session()
        proxied.trust_env = False
        resp = proxied.get(url, timeout=timeout, headers=headers, proxies=proxies)
        resp.raise_for_status()
        return resp.text


def _find_matching_delimiter(text, start, open_ch, close_ch):
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == '\\':
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('Unbalanced delimiter starting at %d' % start)


def _js_to_json(src):
    out = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if src[j] == '\\':
                    j += 2
                elif src[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            out.append(src[i:j])
            i = j
        elif src.startswith('!0', i):
            out.append('true')
            i += 2
        elif src.startswith('!1', i):
            out.append('false')
            i += 2
        elif ch == '.' and (i == 0 or not src[i - 1].isdigit()) and i + 1 < n and src[i + 1].isdigit():
            out.append('0.')
            i += 1
        elif ch in '{,' and i + 1 < n:
            out.append(ch)
            i += 1
            if src[i] != '"':
                match = re.match(r'([^:{}\[\],"\s]+):', src[i:])
                if match:
                    out.append('"' + match.group(1) + '":')
                    i += len(match.group(0))
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _extract_module_body(chunk_js):
    anchor = chunk_js.find('CITY_FATIGUES:()=>')
    if anchor == -1:
        raise ValueError('CITY_FATIGUES export not found in JS chunk')
    arrow_pos = chunk_js.rfind('=>{', 0, anchor)
    if arrow_pos == -1:
        raise ValueError('Module arrow function start not found')
    body_start = arrow_pos + 2
    body_end = _find_matching_delimiter(chunk_js, body_start, '{', '}')
    return chunk_js[body_start:body_end]


def _parse_export_vars(module_body):
    anchor = module_body.find('CITY_FATIGUES:()=>')
    brace_start = module_body.rfind('{', 0, anchor)
    brace_end = _find_matching_delimiter(module_body, brace_start, '{', '}')
    export_obj = module_body[brace_start:brace_end]
    mapping = {}
    for export_name in TARGET_EXPORTS:
        match = re.search(r'\b%s:\(\)=>([A-Za-z_$][\w$]*)' % re.escape(export_name), export_obj)
        if not match:
            raise ValueError('Export binding not found for %s' % export_name)
        mapping[export_name] = match.group(1)
    return mapping


def _extract_var_json(module_body, var_name):
    pattern = re.compile(r'(?:var |let |const |,)%s=([{\[])' % re.escape(var_name))
    match = pattern.search(module_body)
    if not match:
        raise ValueError('Variable assignment not found for %s' % var_name)
    val_start = match.start(1)
    open_ch = match.group(1)
    close_ch = '}' if open_ch == '{' else ']'
    val_end = _find_matching_delimiter(module_body, val_start, open_ch, close_ch)
    return json.loads(_js_to_json(module_body[val_start:val_end]))


def _trim_products(products):
    trimmed = []
    for product in products:
        trimmed.append({
            'name': product['name'],
            'type': product.get('type', ''),
            'buyPrices': product.get('buyPrices', {}),
            'sellPrices': {c: p for c, p in (product.get('sellPrices') or {}).items() if p},
            'buyLot': product.get('buyLot', {}),
        })
    return trimmed


def sync_columba_data(output_path=OUTPUT_PATH):
    html = http_get_text(COLUMBA_BASE_URL + '/route')
    chunks = sorted(set(re.findall(r'/_next/static/chunks/[a-zA-Z0-9_./-]+\.js', html)))
    if not chunks:
        raise RuntimeError('No JS chunks found on /route page')

    module_body = None
    for chunk_path in chunks:
        chunk_js = http_get_text(COLUMBA_BASE_URL + chunk_path)
        if 'CITY_FATIGUES:()=>' in chunk_js:
            module_body = _extract_module_body(chunk_js)
            break
    if module_body is None:
        raise RuntimeError('Static data module with CITY_FATIGUES not found in any JS chunk')

    export_vars = _parse_export_vars(module_body)
    cities = _extract_var_json(module_body, export_vars['CITIES'])
    city_attach = _extract_var_json(module_body, export_vars['CITY_ATTACH_LIST'])
    city_fatigues = _extract_var_json(module_body, export_vars['CITY_FATIGUES'])
    city_with_prestige = _extract_var_json(module_body, export_vars['CITY_WITH_PRESTIGE'])
    products = _trim_products(_extract_var_json(module_body, export_vars['PRODUCTS']))
    resonance_skills = _extract_var_json(module_body, export_vars['RESONANCE_SKILLS'])

    assert len(cities) >= 20, 'Unexpected cities count: %d' % len(cities)
    assert len(products) >= 200, 'Unexpected products count: %d' % len(products)
    assert len(city_fatigues) >= 190, 'Unexpected fatigues count: %d' % len(city_fatigues)
    assert len(resonance_skills) >= 50, 'Unexpected skills count: %d' % len(resonance_skills)

    payload = {
        'cities': cities,
        'city_attach': city_attach,
        'city_with_prestige': city_with_prestige,
        'city_fatigues': city_fatigues,
        'products': products,
        'resonance_skills': resonance_skills,
    }
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    print(
        'Synced columba_data.json: %d products, %d cities, %d fatigues, %d skills'
        % (len(products), len(cities), len(city_fatigues), len(resonance_skills))
    )
    return payload


if __name__ == '__main__':
    sync_columba_data()
