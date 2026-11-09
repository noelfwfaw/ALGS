"""The buy list of an exchange sub shop: `<task>.Filter` and `<task>.Purchases`.

One OCR pass misreads one character now and then (调度券 came back as 调渡券,
as 调券, and correctly, depending on how much of the card frame the crop kept),
so every title is read twice, at two crop margins, and the filter matches when
either read hits an include and neither read hits an exclusion. Includes also
tolerate one missing character (调度券 hides inside the misread 调渡券 as soon
as the whole character set but one is there); exclusions stay strict, a fuzzy
exclusion would tar neighbours such as 精英调度券 with 演习券's brush.

Purchases are a filter in the style of the AzurLane event shop: a switch
`<task>.Filter` (全部 / 自定义 / 不买) and a list `<task>.Purchases`, one rule
per line, in which `>` separates alternatives and a leading `!` excludes. A card
is bought when one line hits the OCR'd name and no exclusion does, so monthly
renames survive as long as one keyword does.

A mixin, not a `UI`: it only decides what to buy. The task brings the config.
"""

import re

from module.logger import logger


class ShopFilter:
    """Which cards of the shelf the user asked for. Assumes `self.config`."""

    CONFIG_TASK = None

    def shop_config(self, key):
        """One setting of this shop's own task, e.g. `Filter`."""
        return getattr(self.config, f'{self.CONFIG_TASK}_{key}', None)

    def shop_filter_init(self):
        """
        Load `Filter` and `Purchases` of this shop's task.

        Filter is a switch in the style of the AzurLane event shop: 全部 buys
        every card left after the `!` lines, 不买 buys nothing, 自定义 follows
        the list. The `!` lines hold in every mode, so an excluded item stays
        unbought even when the switch is flipped to 全部.

        The list is one rule per line, `#` starts a comment. Inside a line
        `>` separates names, and every name is bought in the order it was
        written: top to bottom, left to right. A line starting with `!`
        excludes; an entry starting with `!` excludes too, which is how
        one-line lists of older configs are written - they are rewritten into
        the one-rule-per-line form on first sight, so the settings page shows
        the shape the list has.
        """
        mode = str(self.shop_config('Filter') or '自定义')
        raw = str(self.shop_config('Purchases') or '')
        normalized = self.shop_normalize_filter(raw)
        if normalized != raw:
            logger.info('Shop filter rewritten in the one-rule-per-line form')
            setattr(self.config, f'{self.CONFIG_TASK}_Purchases', normalized)
            raw = normalized

        self.shop_include = []
        self.shop_exclude = []
        rule = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            excluded = line.startswith('!')
            body = line[1:] if excluded else line
            for part in re.split(r'[>＞]', body):
                part = part.strip()
                if not part:
                    continue
                if part.startswith('!'):
                    # An entry of a plain line may carry its own `!`; strip it
                    # once, here, and only here - the line's own `!` was taken
                    # off above, and stripping again would eat a character of
                    # the keyword (`!盾币` became `币`).
                    part = part[1:].strip()
                    if part:
                        self.shop_exclude.append(part)
                elif excluded:
                    self.shop_exclude.append(part)
                else:
                    # Every wanted name is its own priority level, in the order
                    # it was written: top to bottom, left to right.
                    self.shop_include.append((rule, part))
                    rule += 1

        if mode == '不买':
            self.shop_include = []
        elif mode == '全部':
            # An empty keyword sits inside every name.
            self.shop_include = [(0, '')]
        # How many priority levels the list has; the sweep buys them in order.
        self.shop_rule_count = max((rank for rank, _ in self.shop_include),
                                   default=-1) + 1
        logger.attr('Shop filter', f'{mode}: {len(self.shop_include)} include, '
                                   f'{len(self.shop_exclude)} exclude, {rule} rules')

    @staticmethod
    def shop_normalize_filter(raw):
        """
        Rewrite an old one-line list (`A>B>!C`) as one rule per line. Lists
        that already use lines, or that carry no `!` at all, are left as the
        user wrote them.

        Each include of the old form becomes its own line, in the order it was
        written: the order is the priority now (`shop_filter_rank()`), and the
        old form is the only place where the user's order survives.
        """
        if '\n' in raw or '!' not in raw:
            return raw
        include, exclude = [], []
        for part in re.split(r'[>＞]', raw):
            part = part.strip()
            if not part:
                continue
            if part.startswith('!'):
                exclude.append(part[1:].strip())
            else:
                include.append(part)
        lines = list(include)
        lines += [f'!{word}' for word in exclude if word]
        return '\n'.join(lines)

    def shop_filter_match(self, card):
        """
        Args:
            card (tuple): (row, x_left, x_right, name_a, name_b).

        Returns:
            bool: If the card should be bought - an include may hit either
            read, but an exclusion on any read wins.
        """
        return self.shop_filter_rank(card) is not None

    def shop_filter_rank(self, card):
        """
        How early the list asks for a card; None when it is not wanted.

        The list is read in the order it was written: top to bottom, left to
        right within a line. 残响 is bought before 调度券 before 自选水晶.
        Exclusion still beats every include.

        Args:
            card (tuple): (row, x_left, x_right, name_a, name_b).

        Returns:
            int | None: 0 for the first wanted name, 1 for the next, ...; or
            None when the card is excluded or no name matches.
        """
        names = card[3:]
        if any(word in name for name in names for word in self.shop_exclude):
            return None
        for rank, word in self.shop_include:
            if any(self.shop_keyword_hit(word, name) for name in names):
                return rank
        return None

    @staticmethod
    def shop_keyword_hit(word, name):
        """
        One include keyword against one OCR read, with one character of slack:
        the OCR drops and swaps single characters (度 came back as 渡), but the
        rest of the keyword is still there. Counted as a character multiset, so
        a keyword never matches by repeating one lucky character.

        Args:
            word (str): Filter entry.
            name (str): OCR'd card title.

        Returns:
            bool: If the keyword is in the name, or all but one of its
            characters are.
        """
        if word in name:
            return True
        if len(word) < 2:
            return False
        missing = sum(1 for ch in set(word) if name.count(ch) < word.count(ch))
        return missing == 1
