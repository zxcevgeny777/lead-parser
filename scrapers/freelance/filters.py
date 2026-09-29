"""Centralized filter for freelance website development orders and tasks.
Ensures strict thematic relevance (websites only) and excludes competitor offers.
"""
import re
from typing import Optional

# Positive keywords indicating a website / landing / web development task
WEB_POSITIVE_PATTERNS = [
    r'сайт\w*',
    r'лендинг\w*',
    r'landing\w*',
    r'лэндинг\w*',
    r'тильд\w*',
    r'tilda\w*',
    r'интернет[- ]магазин\w*',
    r'онлайн[- ]магазин\w*',
    r'e[- ]commerce',
    r'верстк\w*',
    r'сверстать',
    r'wordpress',
    r'вордпресс',
    r'битрикс\w*',
    r'bitrix\w*',
    r'webflow',
    r'modx',
    r'opencart',
    r'joomla',
    r'drupal',
    r'веб[- ]дизайн\w*',
    r'дизайн сайта\w*',
    r'веб[- ]разработ\w*',
    r'разработка сайта\w*',
    r'создание сайта\w*',
    r'редизайн\w*',
    r'доработка сайта\w*',
    r'доработать сайт\w*',
    r'правки на сайте\w*',
    r'натянуть на cms',
    r'квиз\w*',
    r'frontend\w*',
    r'фронтенд\w*',
]

# Irrelevant keywords: strictly non-web tasks
IRRELEVANT_PATTERNS = [
    r'\b(?:smm|смм)\b',
    r'\b(?:рилс|reels|тикток|tiktok|сторис|stories)\b',
    r'\b(?:таргет\w*|таргетолог\w*|директолог\w*)\b',
    r'\b(?:логотип\w*|лого\b|фирменн\w+ стил\w*)',
    r'\b(?:полиграфи\w*|визитк\w*|листовк\w*|буклет\w*|вывеск\w*|абонемент\w*)',
    r'\b(?:видеомонтаж\w*|монтаж\w* видео|озвучк\w*|ролик\w*|монтажер\w*)',
    r'\b(?:1с|1c)\b',
    r'\b(?:сисадмин\w*|системный администратор\w*|devops|чпу|dxf|чертеж\w*)',
    r'\b(?:копирайт\w*|рерайт\w*|написание статей|переводчик\w*)\b',
    r'\b(?:телемаркетолог\w*|менеджер\w* по продаж\w*|sales[- ]менеджер\w*|обработчик трафика|qa manager|тестировщик\w*)',
]

# Kufar competitor/studio advertisement patterns (people offering services rather than tasks)
EXCLUDE_SELLER_TERMS = [
    r'наш\w* опыт\b',
    r'создаем сайты',
    r'предлага\w+ услуги',
    r'портфолио',
    r'гарантия качества',
    r'веб[- ]студи\w+',
    r'наша команда',
    r'частный мастер',
    r'наши работы',
    r'любой сложности',
    r'опыт более',
    r'создам сайт',
    r'профессиональн\w+ разработк\w*',
    r'профессиональн\w+ создани\w*',
    r'принимаем заказы'
]

# Positive client demand intent (used to filter classifieds like Kufar)
DEMAND_TERMS = [
    r'\bтребуется\b',
    r'\bищу\b',
    r'\bищем\b',
    r'\bнужен\b',
    r'\bнужна\b',
    r'\bнеобходимо\b',
    r'\bдоработать\b',
    r'\bпеределать\b',
    r'\bв команду\b',
    r'\bзаказ на\b',
    r'\bв поисках\b'
]


def is_valid_web_task(title: str, desc: str = "", query: str = "") -> bool:
    """Verifies that a task is genuinely related to website development and not an irrelevant topic."""
    combined = f"{title} {desc}".lower()

    # 1. Must match at least one positive web development pattern
    has_web = any(re.search(p, combined) for p in WEB_POSITIVE_PATTERNS)
    if not has_web:
        return False

    # 2. Check for irrelevant topics (SMM, logos, 1C, video editing, etc.)
    has_irrelevant = any(re.search(p, combined) for p in IRRELEVANT_PATTERNS)
    if has_irrelevant:
        # If an irrelevant keyword exists, only allow if title explicitly mentions a website
        title_low = title.lower()
        title_has_web = any(
            re.search(p, title_low)
            for p in [r'сайт\w*', r'лендинг\w*', r'landing\w*', r'тильд\w*', r'tilda\w*', r'магазин\w*', r'верстк\w*']
        )
        if not title_has_web:
            return False

    # 3. If a specific custom query was passed by the user (e.g. "Tilda", "WordPress", "Битрикс")
    if query:
        clean_q = query.lower().strip()
        q_words = [w for w in re.split(r'[\s,]+', clean_q) if len(w) > 2]
        # Ignore generic stop words
        specific_words = [
            w for w in q_words
            if w not in ["сайт", "разработка", "веб", "web", "фриланс", "создание"]
        ]
        if specific_words:
            if not all(w in combined for w in specific_words):
                return False

    return True


def is_valid_kufar_client_task(title: str, desc: str = "") -> bool:
    """Filters Kufar listings to ensure it's a real client looking for a specialist,

    not a competing agency or freelancer advertising their own services.
    """
    combined = f"{title} {desc}".lower()

    # 1. Must contain client demand intent
    has_demand = any(re.search(p, combined) for p in DEMAND_TERMS)
    if not has_demand:
        return False

    # 2. Must not contain web agency brag words
    is_seller = any(re.search(p, combined) for p in EXCLUDE_SELLER_TERMS)
    if is_seller:
        return False

    return True


def clean_bot_title_and_price(raw_text: str):
    """Cleans up Telegram bot prefixes and extracts structured title and price."""
    # Price
    price_match = re.search(r'💎\s*Награда:\s*([^\n⏳]+)', raw_text)
    if price_match:
        price = price_match.group(1).strip()
    else:
        # Generic price regex
        p_match = re.search(
            r'(?i)(?:бюджет|оплата|цена|ставка|стоимость|от|до)?\s*(?:от|до)?\s*(\d+[\s\d]*\s*(?:руб|р|byn|usd|\$|₽|грн))',
            raw_text
        )
        price = p_match.group(0).strip() if p_match else "По договоренности"

    # Clean lines
    lines = [
        re.sub(r'^[⛏📌👉💎⏳#📜\s]+', '', l).strip()
        for l in raw_text.split('\n')
        if l.strip() and not l.strip().startswith(('⏳', '#', '📜', '💎', 'Публикация:'))
    ]

    title = lines[0][:90] if lines else raw_text[:90]
    desc = " ".join(lines[1:])[:260] if len(lines) > 1 else ""

    return title, price, desc
