"""30-day caravan profit logger and daily trend summary for 雷索纳斯 (Resonance Solstice)."""

from datetime import datetime, timedelta
import html
import json
import os
import re

PROFIT_LOG_PATH = os.path.join('config', 'state', 'resonance_profit_log.json')
PROFIT_RETENTION_DAYS = 30
MAX_SINGLE_PROFIT = 50_000_000


def profit_day_key(now=None):
    """Return YYYY-MM-DD key anchored at 05:00 server reset."""
    cur = now or datetime.now()
    return (cur - timedelta(hours=5)).strftime('%Y-%m-%d')


def parse_sell_profit_text(text):
    """Parse OCR profit string such as '+1,234,567' or '-45600' into signed int, or None."""
    cleaned = str(text or '').replace(',', '').replace(' ', '').strip()
    if not cleaned:
        return None
    match = re.search(r'([+-]?\d+)', cleaned)
    if not match:
        return None
    try:
        val = int(match.group(1))
    except ValueError:
        return None
    return val if abs(val) <= MAX_SINGLE_PROFIT else None


def _read_profit_store(path):
    """Load JSON profit store tolerantly; return empty dict on missing or corrupt files."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_profit_store(payload, path):
    """Atomically write profit store JSON to disk."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _prune_old_days(days_dict, keep_days=PROFIT_RETENTION_DAYS, now=None):
    """Return subset of `days_dict` falling within the rolling `keep_days` window."""
    if not isinstance(days_dict, dict):
        return {}
    base_day = datetime.strptime(profit_day_key(now), '%Y-%m-%d').date()
    cutoff = (base_day - timedelta(days=max(1, int(keep_days)) - 1)).strftime('%Y-%m-%d')
    return {
        k: v for k, v in days_dict.items()
        if isinstance(k, str) and len(k) == 10 and k >= cutoff and isinstance(v, dict)
    }


def record_trade_profit(config_name, profit, from_city='', to_city='', estimated=False,
                        path=PROFIT_LOG_PATH, now=None, restock_used=None):
    """Append one completed sell profit to `config_name`'s rolling 30-day ledger."""
    cur = now or datetime.now()
    key = str(config_name or 'default')
    day_key = profit_day_key(cur)
    val = int(profit)

    store = _read_profit_store(path)
    inst = store.get(key)
    days = _prune_old_days(inst.get('days') if isinstance(inst, dict) else {}, now=cur)
    day_entry = days.get(day_key)
    if not isinstance(day_entry, dict):
        day_entry = {'total': 0, 'count': 0, 'trades': []}
    trades = list(day_entry.get('trades') or [])
    trade = {
        'time': cur.strftime('%H:%M:%S'),
        'from': str(from_city or ''),
        'to': str(to_city or ''),
        'profit': val,
        'estimated': bool(estimated),
    }
    if restock_used is not None:
        trade['restock_used'] = int(restock_used)
    trades.append(trade)
    updated = {
        'total': int(day_entry.get('total', 0)) + val,
        'count': int(day_entry.get('count', 0)) + 1,
        'trades': trades,
    }
    days[day_key] = updated
    store[key] = {'days': days}
    _write_profit_store(store, path)
    return updated


def load_profit_days(config_name, path=PROFIT_LOG_PATH):
    """Return {day_key: day_dict} for `config_name`, or empty dict."""
    key = str(config_name or 'default')
    inst = _read_profit_store(path).get(key)
    days = inst.get('days') if isinstance(inst, dict) else None
    return days if isinstance(days, dict) else {}


def format_profit_delta(delta, pct):
    """Format day-over-day profit delta into (display_text, css_color)."""
    if delta is None:
        return '—', '#6c757d'
    if delta > 0:
        text = f'▲ +{delta:,}' + (f' (+{pct:.1f}%)' if pct is not None else '')
        return text, '#28a745'
    if delta < 0:
        text = f'▼ {delta:,}' + (f' ({pct:.1f}%)' if pct is not None else '')
        return text, '#dc3545'
    return '0 (0.0%)', '#6c757d'


def format_delta_html(text, color):
    """Wrap formatted delta string in a colored bold inline HTML span."""
    return f'<span style="color: {color}; font-weight: 600;">{html.escape(text)}</span>'


def summarize_restock_usage(trades):
    """Summarize known actual restock-book usage without treating missing values as zero."""
    total = 0
    known = 0
    missing = 0
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        used = trade.get('restock_used')
        if used is None:
            missing += 1
        else:
            total += int(used)
            known += 1
    text = '—' if missing and not known else f'{total:,}'
    if missing and known:
        text += f'（仅已记录，缺 {missing} 笔）'
    return {'total': total if known or not missing else None, 'text': text,
            'known_count': known, 'unknown_count': missing}


def _compute_daily_rows(days):
    """Compute day-over-day deltas chronologically and return rows sorted newest first."""
    chrono = []
    prev_total = None
    for day_key in sorted(days.keys()):
        entry = days[day_key]
        total = int(entry.get('total', 0))
        count = int(entry.get('count', 0))
        if prev_total is None:
            delta, pct = None, None
        else:
            delta = total - prev_total
            pct = round(delta / float(abs(prev_total)) * 100.0, 1) if prev_total else None
        delta_text, delta_color = format_profit_delta(delta, pct)
        chrono.append({
            'date': day_key,
            'count': count,
            'total': total,
            'delta': delta,
            'pct': pct,
            'delta_text': delta_text,
            'delta_color': delta_color,
        })
        prev_total = total
    chrono.reverse()
    return chrono


def summarize_profit_history(config_name, path=PROFIT_LOG_PATH, now=None, days_limit=PROFIT_RETENTION_DAYS):
    """Build today summary, per-trade list, and rolling 30-day daily trend rows."""
    cur = now or datetime.now()
    today_key = profit_day_key(cur)
    days = _prune_old_days(load_profit_days(config_name, path=path), keep_days=days_limit, now=cur)
    daily_rows = _compute_daily_rows(days)
    row_by_date = {row['date']: row for row in daily_rows}

    today_entry = days.get(today_key, {})
    today_total = int(today_entry.get('total', 0)) if isinstance(today_entry, dict) else 0
    today_count = int(today_entry.get('count', 0)) if isinstance(today_entry, dict) else 0
    today_avg = round(today_total / today_count) if today_count > 0 else 0
    today_trades = list(reversed(today_entry.get('trades') or [])) if isinstance(today_entry, dict) else []

    today_row = row_by_date.get(today_key)
    today_delta = today_row['delta'] if today_row else None
    today_pct = today_row['pct'] if today_row else None
    today_delta_text, today_delta_color = format_profit_delta(today_delta, today_pct)

    total_30d = sum(row['total'] for row in daily_rows)
    count_30d = sum(row['count'] for row in daily_rows)
    active_days = len(daily_rows)
    avg_day_30d = round(total_30d / active_days) if active_days > 0 else 0
    best_row = max(daily_rows, key=lambda r: r['total'], default=None)
    trades_30d = [trade for day in days.values() if isinstance(day, dict) for trade in (day.get('trades') or [])]

    overview_line = ''
    if today_count > 0:
        suffix = f'{today_count} 笔｜{today_delta_text}' if today_delta is not None else f'{today_count} 笔'
        overview_line = f'今日利润 {today_total:,}（{suffix}）'

    return {
        'today_key': today_key,
        'today_total': today_total,
        'today_count': today_count,
        'today_avg': today_avg,
        'today_delta': today_delta,
        'today_pct': today_pct,
        'today_delta_text': today_delta_text,
        'today_delta_color': today_delta_color,
        'today_trades': today_trades,
        'total_30d': total_30d,
        'count_30d': count_30d,
        'active_days': active_days,
        'avg_day_30d': avg_day_30d,
        'best_day': (best_row['date'], best_row['total']) if best_row else None,
        'today_restock': summarize_restock_usage(today_trades),
        'restock_30d': summarize_restock_usage(trades_30d),
        'daily_rows': daily_rows,
        'overview_line': overview_line,
    }
