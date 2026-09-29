"""AI Pitch and Cold Outreach Generator for Qualified Business Leads.

Generates high-converting, personalized 1-on-1 outreach pitches:
- 💬 WhatsApp / Telegram messenger direct pitch
- 📞 30-second telephone cold call script
Includes both a high-performance algorithmic generator and an optional Gemini LLM integration.
"""
import json
import os
import re
import urllib.request
import urllib.parse
from typing import Tuple, Optional

from .models import Lead, WebsiteStatus, LeadPriority


def generate_algorithmic_pitch(lead: Lead) -> Tuple[str, str]:
    """Generates tailored, high-converting outreach message and call script based on lead attributes."""
    name = lead.name.strip()
    city = lead.city.strip() if lead.city else "вашем городе"
    category = lead.category.strip() if lead.category else "вашей сфере"
    rating_str = f"{lead.rating:.1f}" if lead.rating else "высокий"
    rev_count = lead.reviews_count or 0
    audit_summary = lead.site_audit_summary or ""

    # 1. SCENARIO: Ad pixel detected, but no mobile viewport or broken site (SUPER HOT)
    if "НЕТ МОБИЛКИ" in audit_summary and "КРУТЯТ РЕКЛАМУ" in audit_summary:
        msg = (
            f"Здравствуйте, {name}! Обратил внимание на ваше продвижение в {city}. "
            f"Заметил критическую проблему: при переходе с рекламы со смартфонов сайт не адаптирован "
            f"под мобильные экраны. Сейчас более 70% клиентов заходят с телефонов — из-за сломанной верстки "
            f"рекламный бюджет сливается впустую. Мы можем за 48 часов обновить сайт на ультрабыстрый "
            f"мобильный лендинг и поднять конверсию в 2–3 раза. Прислать короткий видео-разбор?"
        )
        call = (
            f"Здравствуйте! Звоню коротко по делу: обратил внимание на вашу платную рекламу в интернете. "
            f"Ваш сайт сейчас совсем не оптимизирован под смартфоны — мобильные клиенты уходят, не дозвонившись. "
            f"Мы бесплатно подготовили экспресс-разбор 3 главных ошибок посадочной страницы. "
            f"Куда удобнее отправить ссылку — в WhatsApp или Telegram?"
        )
        return msg, call

    # 2. SCENARIO: Has website, but NO mobile version
    if "НЕТ МОБИЛКИ" in audit_summary:
        msg = (
            f"Добрый день, {name}! У вас отличный бизнес в {city}, но ваш сайт не адаптирован "
            f"для мобильных телефонов (мелкий текст, блоки не помещаются в экран). "
            f"Поисковики Яндекс и Google сейчас понижают такие сайты в выдаче. "
            f"Мы специализируемся на мобильном редизайне под ключ за 3 дня. "
            f"Хотите пришлю пример, как будет выглядеть современная мобильная версия вашей компании?"
        )
        call = (
            f"Добрый день! Подскажите, кто у вас отвечает за сайт и рекламу? Увидел вашу компанию в {city}, "
            f"но при входе с телефона сайт не адаптирован, шрифты разъезжаются. "
            f"Мы как раз подготовили пример современного адаптивного дизайна для {category}. "
            f"Сбросить вам ссылку в мессенджер посмотреть?"
        )
        return msg, call

    # 3. SCENARIO: NO WEBSITE AT ALL (Classic High-converting Hot Lead)
    if lead.website_status == WebsiteStatus.NO_WEBSITE or not lead.website:
        reviews_mention = f"отличный рейтинг {rating_str} и {rev_count} отзывов на картах" if rev_count >= 5 else "активный бизнес на картах"
        msg = (
            f"Здравствуйте! Увидел компанию «{name}» в {city} — у вас {reviews_mention}, видно, "
            f"что клиенты вам доверяют. Но заметил, что у вас совсем нет собственного сайта / онлайн-записи. "
            f"Из-за этого до 40% клиентов из поиска Яндекса и Google уходят к вашим прямым конкурентам. "
            f"Мы создаем современные продающие сайты и Telegram Mini Apps для {category} за 3 дня. "
            f"Давайте пришлю короткое демо, как это может выглядеть для вас?"
        )
        call = (
            f"Здравствуйте! Меня зовут Евгений. Увидел вашу компанию на картах в {city} — у вас {reviews_mention}. "
            f"Но обратил внимание, что у вас нет своего сайта, из-за чего клиенты из поисковиков уходят к конкурентам. "
            f"Мы разрабатываем быстрые сайты и Telegram-боты для {category}. "
            f"Хочу бесплатно отправить вам пример готовой структуры. Куда удобнее — в WhatsApp или Telegram?"
        )
        return msg, call

    # 4. SCENARIO: ONLY TAPLINK, BOOKING WIDGET OR SOCIALS
    w_lower = str(lead.website).lower() if lead.website else ""
    is_booking_or_taplink = (
        lead.website_status in (WebsiteStatus.TAPLINK, WebsiteStatus.SOCIAL)
        or any(b in w_lower for b in ["dikidi", "yclients", "alteg", "rubitime", "taplink", "linktr.ee"])
    )

    if is_booking_or_taplink:
        if "dikidi" in w_lower:
            channel_name = "онлайн-запись DIKIDI"
        elif "yclients" in w_lower:
            channel_name = "виджет онлайн-записи YClients"
        elif "alteg" in w_lower:
            channel_name = "онлайн-запись Altegio"
        elif "taplink" in w_lower:
            channel_name = "страница Taplink"
        elif "instagram" in lead.social_links:
            channel_name = "профиль Instagram"
        elif "vk" in lead.social_links:
            channel_name = "сообщество ВКонтакте"
        else:
            channel_name = "сервис онлайн-записи"

        msg = (
            f"Добрый день, {name}! Заметил, что у вас в {city} настроен {channel_name}. "
            f"Это удобно для постоянных клиентов, однако без собственного полноценного сайта / Telegram Mini App "
            f"вы теряете до 40% новых клиентов из органического поиска Яндекса и Google. "
            f"Мы создаем современные продающие сайты с бесшовной интеграцией вашей текущей записи за 3 дня. "
            f"Хотите пришлю пример первого экрана для сферы «{category}»?"
        )
        call = (
            f"Добрый день! Обратил внимание на вашу компанию в {city} — здорово, что у вас подключен {channel_name}. "
            f"Но из-за отсутствия своего сайта в поисковиках новые клиенты уходят к конкурентам. "
            f"Мы упаковываем компании в современные сайты под ключ с сохранением вашей записи. "
            f"Куда удобнее сбросить короткое демо — в WhatsApp или Telegram?"
        )
        return msg, call

    # 5. SCENARIO: HAS WEBSITE (Offer modernization, Speed boost, or Telegram Mini App)
    if not lead.website or any(eng in w_lower for eng in ["yandex.", "google.", "2gis.", "apple."]):
        # Sanity fallback: if site was invalid/search engine, pitch as no-website lead
        reviews_mention = f"отличный рейтинг {rating_str} и {rev_count} отзывов на картах" if rev_count >= 5 else "активный бизнес на картах"
        msg = (
            f"Здравствуйте! Увидел компанию «{name}» в {city} — у вас {reviews_mention}. "
            f"Но заметил, что у вас нет собственного оптимизированного сайта. "
            f"Из-за этого клиенты из поиска Яндекса и Google уходят к прямым конкурентам. "
            f"Мы создаем современные продающие сайты и Telegram Mini Apps для {category} за 3 дня. "
            f"Давайте пришлю короткое демо, как это может выглядеть для вас?"
        )
        call = (
            f"Здравствуйте! Меня зовут Евгений. Увидел вашу компанию на картах в {city} — у вас {reviews_mention}. "
            f"Обратил внимание, что у вас нет своего сайта в поисковиках. "
            f"Мы разрабатываем быстрые сайты и Telegram-боты для {category}. "
            f"Хочу бесплатно отправить вам пример готовой структуры. Куда удобнее — в WhatsApp или Telegram?"
        )
        return msg, call

    msg = (
        f"Здравствуйте, {name}! Изучил ваш сайт {lead.website}. Компания работает отлично, "
        f"но сейчас главный тренд — перенос онлайн-заказа и каталога прямо в Telegram (Telegram Mini Apps), "
        f"где клиенты оформляют заявки в 2 клика без долгой загрузки и ожидания ответа менеджера. "
        f"Мы разрабатываем такие интеграции для сферы «{category}». "
        f"Могу показать 1-минутное видео работы такого решения?"
    )
    call = (
        f"Здравствуйте! Звоню по поводу сайта вашей компании. Изучил ваш ресурс в {city} — вы круто работаете. "
        f"Мы внедряем дополнительный канал продаж через Telegram Mini Apps и умных ИИ-консультантов, "
        f"который привлекает молодую платежеспособную аудиторию. Скажите, кому из руководителей можно отправить демо?"
    )
    return msg, call


def generate_gemini_pitch(lead: Lead, api_key: str) -> Optional[Tuple[str, str]]:
    """Calls Google Gemini API (Interactions API / v1beta generateContent) for hyper-personalized pitch."""
    if not api_key:
        return None

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        prompt = (
            f"Ты лучший эксперт по B2B-продажам веб-сайтов и Telegram Mini Apps.\n"
            f"Создай 2 текста для клиента:\n"
            f"1. Короткое сообщение в WhatsApp/Telegram (3-4 предложения, без клише, с конкретным фактом и вопросом в конце).\n"
            f"2. Скрипт холодного звонка на 30 секунд.\n"
            f"Данные о компании:\n"
            f"- Название: {lead.name}\n"
            f"- Город: {lead.city}\n"
            f"- Ниша: {lead.category}\n"
            f"- Статус сайта: {lead.website_status.value} (URL: {lead.website or 'нет'})\n"
            f"- Рейтинг: {lead.rating}, Отзывов: {lead.reviews_count}\n"
            f"- Аудит сайта: {lead.site_audit_summary or 'нет'}\n\n"
            f"Верни СТРОГО JSON формат:\n"
            f'{{"messenger_pitch": "...", "call_script": "..."}}'
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed = json.loads(text)
                return parsed.get("messenger_pitch", ""), parsed.get("call_script", "")
    except Exception:
        pass
    return None


def enrich_lead_with_pitch(lead: Lead, gemini_api_key: str = "") -> Lead:
    """Enriches lead with personalized messenger pitch and call script."""
    # Try Gemini if key available, else algorithmic
    if gemini_api_key:
        gemini_res = generate_gemini_pitch(lead, gemini_api_key)
        if gemini_res:
            lead.ai_pitch, lead.call_script = gemini_res
            return lead

    msg, call = generate_algorithmic_pitch(lead)
    lead.ai_pitch = msg
    lead.call_script = call
    return lead
