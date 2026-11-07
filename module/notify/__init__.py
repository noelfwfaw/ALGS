def handle_notify(*args, **kwargs):
    # Lazy import onepush
    from module.notify.notify import handle_notify
    return handle_notify(*args, **kwargs)


def load_onepush_conf(raw):
    # Lazy import onepush
    from module.notify.notify import load_onepush_conf
    return load_onepush_conf(raw)


def notify_error(config_name, message, title='Alas推送', raw_config=None):
    # Lazy import onepush
    from module.notify.notify import notify_error
    return notify_error(config_name, message, title=title, raw_config=raw_config)
