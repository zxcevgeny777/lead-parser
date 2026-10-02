"""Web verification module: checks whether a business has an official website by domain resolution and search."""
import asyncio
import re
import socket
import urllib.parse
import urllib.request
from typing import Optional, Tuple, List

# Transliteration rules for Russian company names (Russian -> Latin domain variants)
TRANSLIT_MAP = {
    'а': ['a'], 'б': ['b'], 'в': ['v', 'w'], 'г': ['g'], 'д': ['d'],
    'е': ['e'], 'ё': ['e', 'yo'], 'ж': ['zh', 'j'], 'з': ['z'], 'и': ['i'],
    'й': ['y', 'i'], 'к': ['k', 'c'], 'л': ['l'], 'м': ['m'], 'н': ['n'],
    'о': ['o'], 'п': ['p'], 'р': ['r'], 'с': ['s'], 'т': ['t'],
    'у': ['u'], 'ф': ['f', 'ph'], 'х': ['h', 'kh'], 'ц': ['ts', 'z', 'c'],
    'ч': ['ch'], 'ш': ['sh'], 'щ': ['sch', 'sh'], 'ъ': [''], 'ы': ['y'],
    'ь': [''], 'э': ['e'], 'ю': ['yu', 'u'], 'я': ['ya', 'ia']
}

AGGREGATOR_DOMAINS = {
    # Search & Maps
    "duckduckgo.com", "yandex.ru", "yandex.by", "yandex.kz", "yandex.com", "yandex.uz", "ya.ru", "ya.by",
    "maps.yandex.ru", "maps.yandex.by", "google.com", "google.ru", "google.by", "maps.google.com",
    "2gis.ru", "2gis.by", "2gis.com", "apple.com", "maps.apple.com", "bing.com", "mail.ru", "dzen.ru",
    "rambler.ru", "wikipedia.org", "wikimapia.org",
    # Booking & Widgets
    "yclients.com", "yclients.site", "dikidi.net", "dikidi.ru", "dikidi.online", "dikidi.app", "dikidi.me",
    "clients.site", "alteg.io", "altegio.com", "rubitime.ru", "gnom.guru", "bnovo.ru", "traveline.ru",
    "taplink.cc", "taplink.ru", "linktr.ee", "hipolink.me", "mssg.me", "meconnect.ru", "msto.me", "aqulas.me",
    # CIS Catalogs & Directories
    "zoon.ru", "zoon.by", "spb.zoon.ru", "msk.zoon.ru", "avito.ru", "yell.ru", "spr.ru", "spr.by",
    "cataloxy.ru", "cataloxy.by", "orgpage.ru", "yp.ru", "vl.ru", "prodoctorov.ru", "docdoc.ru", "sberhealth.ru",
    "allinform.ru", "infomesto.com", "pulscen.ru", "pulscen.by", "tiu.ru", "blizko.ru", "blizko.by",
    "flamp.ru", "otzovik.com", "irecommend.ru", "hh.ru", "superjob.ru", "rabota.ru", "rabota.by", "praca.by",
    "vk.com", "vk.me", "ok.ru", "t.me", "telegram.me", "instagram.com", "facebook.com", "youtube.com", "rutube.ru",
    "checko.ru", "rusprofile.ru", "spark-interfax.ru", "list-org.com", "audit-it.ru", "zachestnyibiznes.ru",
    "synapsenet.ru", "b2b-center.ru", "kwork.ru", "fl.ru", "freelancehunt.com", "weblancer.net",
    # Belarus specific directories & portals
    "onliner.by", "s.onliner.by", "catalog.onliner.by", "baraholka.onliner.by", "kufar.by", "relax.by", "deal.by",
    "tam.by", "103.by", "doska.by", "infopark.by", "tochka.by", "abw.by", "av.by", "irr.by", "b2b.by",
    "kartoteka.by", "infominsk.by", "minsk-in.net", "gorod24.by", "otzyvy.by", "prof-master.by", "flagma.by",
    "ouuo.ru", "ayle.ru", "mn.ayle.ru", "buk.by", "maxi.by", "tut.by", "govorim.by", "minsk.by",
    "vitebsk.biz", "grodno.in", "brest.biz", "mogilev.in", "gomel.in"
}


def is_aggregator_domain(url_or_domain: str) -> bool:
    """Checks if a URL or domain belongs to a known aggregator, directory, booking widget, or search portal."""
    if not url_or_domain:
        return True
    domain = url_or_domain.lower().strip()
    if "://" in domain:
        try:
            domain = urllib.parse.urlparse(domain).netloc.lower()
        except Exception:
            pass
    if domain.startswith("www."):
        domain = domain[4:]
    domain = domain.split(":")[0].split("/")[0]

    # Quick pattern check
    if any(pat in domain for pat in [
        "yandex.", "ya.ru", "ya.by", "google.", "2gis.", "apple.",
        "dikidi.", "yclients.", "taplink.", "linktr.ee", "zoon."
    ]):
        return True

    return any(domain == agg or domain.endswith("." + agg) for agg in AGGREGATOR_DOMAINS)


def _translit_simple(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch in TRANSLIT_MAP:
            out.append(TRANSLIT_MAP[ch][0])
        elif ch.isalnum() or ch in ('-', '_'):
            out.append(ch)
        elif ch.isspace():
            out.append('-')
    joined = "".join(out)
    return re.sub(r'-+', '-', joined).strip('-')


def generate_candidate_domains(company_name: str, city: str = "") -> List[str]:
    """Generates most plausible domain candidates for a given business name."""
    cleaned = re.sub(
        r'(?i)\b(ооо|зао|пао|ип|салон|клиника|центр|студия|магазин|сервис|стоматология|автосервис)\b',
        '',
        company_name
    )
    cleaned = re.sub(r'[«»"“”\'’\(\)]', '', cleaned).strip()
    if not cleaned or len(cleaned) < 2:
        cleaned = company_name.strip()

    simple = _translit_simple(cleaned)
    city_simple = _translit_simple(city) if city else ""

    candidates = set()
    if simple and len(simple) >= 3:
        candidates.add(simple)
        candidates.add(simple.replace('-', ''))
        # Common brand handling: pizza -> dodo-pizza, dodopizza
        if 'pitstsa' in simple:
            candidates.add(simple.replace('pitstsa', 'pizza'))
            candidates.add(simple.replace('pitstsa', 'pizza').replace('-', ''))

        if city_simple:
            candidates.add(f"{simple}-{city_simple}")
            candidates.add(f"{simple.replace('-', '')}{city_simple}")

    # Extract any explicit latin words in name (e.g. "Dodo Pizza", "BMW Service")
    latin_words = re.findall(r'[a-zA-Z0-9]+', company_name.lower())
    if latin_words:
        candidates.add("".join(latin_words))
        candidates.add("-".join(latin_words))

    city_lower = str(city).lower()
    is_by = any(w in city_lower for w in [
        "минск", "брест", "гродно", "витебск", "могилев", "гомель",
        "барановичи", "бобруйск", "пинск", "борисов", "солигорск", "беларусь", "by"
    ])
    is_us_eu = any(w in city_lower for w in ["miami", "new york", "usa", "los angeles", "chicago", "london", "berlin", "warsaw"])

    if is_by:
        tlds = ['.by', '.com', '.ru', '.online', '.бел', '.pro']
    elif is_us_eu:
        tlds = ['.com', '.net', '.org', '.io', '.co', '.us']
    else:
        tlds = ['.ru', '.by', '.com', '.online', '.pro', '.su']

    domains = []
    for c in candidates:
        if 3 <= len(c) <= 35:
            for tld in tlds:
                domains.append(f"{c}{tld}")

    return list(dict.fromkeys(domains))


def check_domain_active_sync(domain: str) -> bool:
    """Checks if domain resolves via DNS and serves an active HTTP/HTTPS website."""
    try:
        # Fast DNS pre-check (< 30ms)
        socket.gethostbyname(domain)
    except Exception:
        return False

    # Verify HTTP/HTTPS response
    for proto in ("https", "http"):
        try:
            url = f"{proto}://{domain}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status in (200, 301, 302, 307, 308):
                    return True
        except Exception:
            continue
    return False


def verify_company_website_sync(company_name: str, city: str = "") -> Tuple[bool, Optional[str]]:
    """Checks if company has an official website via candidate domain resolution and web search."""
    clean_name = company_name.strip()
    if not clean_name or len(clean_name) < 2:
        return False, None

    # 1. Candidate Domain Strategy (concurrent check for 8x speedup)
    candidates = generate_candidate_domains(clean_name, city)[:10]
    if candidates:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as executor:
            future_to_domain = {executor.submit(check_domain_active_sync, d): d for d in candidates}
            for future in as_completed(future_to_domain):
                try:
                    if future.result():
                        return True, f"https://{future_to_domain[future]}"
                except Exception:
                    pass

    # 2. Web Search Strategy (DDG HTML fallback)
    try:
        clean_search_name = re.sub(r'[«»"“”\']', '', clean_name)
        query = f'{clean_search_name} {city} официальный сайт'.strip()
        url = "https://html.duckduckgo.com/html/"
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://html.duckduckgo.com/",
            }
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            # If CAPTCHA challenge is not present
            if "anomaly-modal" not in html:
                raw_hrefs = re.findall(r'<a[^>]+class="[^"]*result__url[^"]*"[^>]+href="([^"]+)"', html)
                if not raw_hrefs:
                    raw_hrefs = re.findall(r'<a[^>]+href="(https?://[^"]+)"', html)

                # Distinctive brand tokens to prevent false-positive associations with random sites/directories
                words = re.findall(r'[a-zA-Zа-яА-Я0-9]{3,}', clean_name.lower())
                generic_stops = {
                    "салон", "красоты", "центр", "студия", "магазин", "сервис", "клиника",
                    "плюс", "люкс", "групп", "room", "club", "bar", "cafe", "minsk", "минск",
                    "ооо", "зао", "пао", "ип"
                }
                name_tokens = set()
                for w in words:
                    if w not in generic_stops:
                        name_tokens.add(w)
                        trans = _translit_simple(w).replace('-', '')
                        if len(trans) >= 3:
                            name_tokens.add(trans)

                for h in raw_hrefs:
                    if not h.startswith("http"):
                        continue
                    try:
                        parsed = urllib.parse.urlparse(h)
                        netloc = parsed.netloc.lower()
                        if netloc.startswith("www."):
                            netloc = netloc[4:]
                        if is_aggregator_domain(netloc):
                            continue

                        # Crucial relevance check:
                        # Netloc must contain at least one brand keyword to be accepted as official website
                        if name_tokens:
                            domain_clean = re.sub(r'[^a-z0-9]', '', netloc)
                            matches_token = any(tok in domain_clean for tok in name_tokens)
                            if not matches_token:
                                continue

                        return True, f"{parsed.scheme}://{parsed.netloc}"
                    except Exception:
                        continue
    except Exception:
        pass

    return False, None


async def verify_company_website(company_name: str, city: str = "") -> Tuple[bool, Optional[str]]:
    """Asynchronous wrapper for verify_company_website_sync."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, verify_company_website_sync, company_name, city)
