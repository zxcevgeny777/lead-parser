"""Curated list of high-converting niches for website design and development services."""
from typing import List, Dict

POPULAR_NICHES: List[Dict[str, str]] = [
    # Автобизнес и транспорт (высокая маржинальность, постоянный поток заявок)
    {"name": "Автосервис", "category": "Автомобили и транспорт", "icon": "🚗"},
    {"name": "Детейлинг", "category": "Автомобили и транспорт", "icon": "✨"},
    {"name": "Кузовной ремонт", "category": "Автомобили и транспорт", "icon": "🚘"},
    {"name": "Автоподбор", "category": "Автомобили и транспорт", "icon": "🔍"},
    {"name": "Срочный выкуп авто", "category": "Автомобили и транспорт", "icon": "💰"},
    {"name": "Чип-тюнинг", "category": "Автомобили и транспорт", "icon": "🏎️"},
    {"name": "Ремонт вмятин без покраски (PDR)", "category": "Автомобили и транспорт", "icon": "🔨"},
    {"name": "Тонировка и бронепленка", "category": "Автомобили и транспорт", "icon": "🛡️"},
    {"name": "Грузовой автосервис", "category": "Автомобили и транспорт", "icon": "🚚"},
    {"name": "Шиномонтаж", "category": "Автомобили и транспорт", "icon": "🛞"},
    {"name": "Автомойка", "category": "Автомобили и транспорт", "icon": "🚿"},
    {"name": "Эвакуатор", "category": "Автомобили и транспорт", "icon": "🚛"},
    {"name": "Квартирные и офисные переезды под ключ", "category": "Автомобили и транспорт", "icon": "📦"},
    {"name": "Шумоизоляция и автозвук", "category": "Автомобили и транспорт", "icon": "🔊"},

    # Строительство и ремонт (высокий средний чек, клиенты активно ищут подрядчиков через сайты)
    {"name": "Ремонт квартир", "category": "Строительство и ремонт", "icon": "🏠"},
    {"name": "Строительство домов", "category": "Строительство и ремонт", "icon": "🏗️"},
    {"name": "Бурение скважин", "category": "Строительство и ремонт", "icon": "💧"},
    {"name": "Септики и автономная канализация", "category": "Строительство и ремонт", "icon": "🚽"},
    {"name": "Фундаменты под ключ", "category": "Строительство и ремонт", "icon": "🧱"},
    {"name": "Кровельные работы", "category": "Строительство и ремонт", "icon": "🔨"},
    {"name": "Остекление балконов и окон", "category": "Строительство и ремонт", "icon": "🪟"},
    {"name": "Заборы и откатные ворота", "category": "Строительство и ремонт", "icon": "🚧"},
    {"name": "Натяжные потолки", "category": "Строительство и ремонт", "icon": "🏢"},
    {"name": "Дизайн интерьера", "category": "Строительство и ремонт", "icon": "🎨"},
    {"name": "Электромонтажные работы", "category": "Строительство и ремонт", "icon": "⚡"},
    {"name": "Сантехника и отопление", "category": "Строительство и ремонт", "icon": "🔧"},
    {"name": "Полусухая стяжка и штукатурка", "category": "Строительство и ремонт", "icon": "📐"},
    {"name": "Ландшафтный дизайн и благоустройство", "category": "Строительство и ремонт", "icon": "🌳"},
    {"name": "Производство и монтаж лестниц", "category": "Строительство и ремонт", "icon": "🪜"},

    # Медицина и бьюти (очень платежеспособная ниша, критически важен продающий сайт)
    {"name": "Стоматология", "category": "Медицина и красота", "icon": "🦷"},
    {"name": "Пластическая и эстетическая хирургия", "category": "Медицина и красота", "icon": "⚕️"},
    {"name": "Наркологическая клиника / Капельницы", "category": "Медицина и красота", "icon": "🏥"},
    {"name": "Косметология", "category": "Медицина и красота", "icon": "💆"},
    {"name": "Психотерапевт / Психолог", "category": "Медицина и красота", "icon": "🧠"},
    {"name": "Салон красоты", "category": "Медицина и красота", "icon": "💅"},
    {"name": "Барбершоп", "category": "Медицина и красота", "icon": "💈"},
    {"name": "Лазерная эпиляция", "category": "Медицина и красота", "icon": "⚡"},
    {"name": "Перманентный макияж", "category": "Медицина и красота", "icon": "💄"},
    {"name": "Массажный салон", "category": "Медицина и красота", "icon": "🌿"},
    {"name": "Ветеринарная клиника", "category": "Медицина и красота", "icon": "🐾"},

    # Услуги для бизнеса и спецтехника (высокая цена лида, окупаемость сайта с 1-2 сделок)
    {"name": "Банкротство физлиц", "category": "Услуги и B2B", "icon": "📋"},
    {"name": "Юридические услуги", "category": "Услуги и B2B", "icon": "⚖️"},
    {"name": "Аренда спецтехники / Манипулятор", "category": "Услуги и B2B", "icon": "🚜"},
    {"name": "Грузоперевозки", "category": "Услуги и B2B", "icon": "📦"},
    {"name": "Вскрытие и замена замков", "category": "Услуги и B2B", "icon": "🔑"},
    {"name": "Бухгалтерское обслуживание", "category": "Услуги и B2B", "icon": "📊"},
    {"name": "Клининговая компания", "category": "Услуги и B2B", "icon": "🧹"},
    {"name": "Химчистка мебели и ковров", "category": "Услуги и B2B", "icon": "🛋️"},
    {"name": "Установка кондиционеров и вентиляции", "category": "Услуги и B2B", "icon": "❄️"},
    {"name": "Сертификация и лицензирование", "category": "Услуги и B2B", "icon": "📜"},
    {"name": "Вывоз мусора и демонтаж", "category": "Услуги и B2B", "icon": "🗑️"},
    {"name": "Памятники и благоустройство захоронений", "category": "Услуги и B2B", "icon": "🪦"},
    {"name": "Монтаж видеонаблюдения и СКУД", "category": "Услуги и B2B", "icon": "📹"},
    {"name": "Ремонт крупной бытовой техники", "category": "Услуги и B2B", "icon": "🧰"},
    {"name": "Склады индивидуального хранения (Self-Storage)", "category": "Услуги и B2B", "icon": "🏬"},

    # Обучение и мероприятия
    {"name": "Банкетный зал", "category": "Обучение и праздники", "icon": "🍽️"},
    {"name": "Кейтеринг и фуршеты", "category": "Обучение и праздники", "icon": "🥂"},
    {"name": "Организация свадеб и мероприятий", "category": "Обучение и праздники", "icon": "💍"},
    {"name": "Автошкола", "category": "Обучение и праздники", "icon": "🚦"},
    {"name": "Детский развивающий центр", "category": "Обучение и праздники", "icon": "🎈"},
    {"name": "Фотостудия", "category": "Обучение и праздники", "icon": "📸"},
    {"name": "Аренда яхт и катеров", "category": "Обучение и праздники", "icon": "🛥️"},

    # Топ-ниши для Беларуси (высокий чек, 80%+ отсутствие нормального сайта)
    {"name": "Коттеджи на сутки и агроусадьбы", "category": "🇧🇾 Топ-чек Беларусь", "icon": "🏡"},
    {"name": "Пригон авто из Европы и США", "category": "🇧🇾 Топ-чек Беларусь", "icon": "🚢"},
    {"name": "Кухни на заказ и корпусная мебель", "category": "🇧🇾 Топ-чек Беларусь", "icon": "🛋️"},
    {"name": "Антикоррозийная обработка авто", "category": "🇧🇾 Топ-чек Беларусь", "icon": "🛡️"},
    {"name": "Перетяжка руля и салона авто", "category": "🇧🇾 Топ-чек Беларусь", "icon": "✂️"},
    {"name": "Аренда бани и сауны", "category": "🇧🇾 Топ-чек Беларусь", "icon": "🪵"},

    # Топ-ниши с высоким чеком для США и Европы ($1,500 - $5,000+ за сайт)
    {"name": "Roofing Contractors", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🔨"},
    {"name": "HVAC Services", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "❄️"},
    {"name": "Plumbing Services", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🔧"},
    {"name": "Solar Panel Installation", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "☀️"},
    {"name": "Home Remodeling", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🏠"},
    {"name": "Tree Service & Removal", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🌳"},
    {"name": "Auto Detailing & Ceramic", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "✨"},
    {"name": "Dental & Orthodontics", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🦷"},
    {"name": "Med Spa & Aesthetics", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "💆"},
    {"name": "Commercial Cleaning", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🧹"},
    {"name": "Pool Installation & Service", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🏊"},
    {"name": "Landscaping & Hardscaping", "category": "🇺🇸/🇪🇺 High-Ticket US/EU", "icon": "🌿"},
]

# Quick popular picks for fast buttons (CIS / Belarus)
QUICK_NICHES = [
    "Коттеджи на сутки и агроусадьбы",
    "Кухни на заказ и корпусная мебель",
    "Пригон авто из Европы и США",
    "Стоматология",
    "Детейлинг",
    "Автосервис",
    "Ремонт квартир",
    "Банкетный зал",
    "Антикоррозийная обработка авто",
    "Натяжные потолки",
    "Косметология",
    "Строительство домов",
    "Ландшафтный дизайн и благоустройство",
    "Памятники и благоустройство захоронений",
]

# Quick high-ticket picks for US and Europe ($1.5k - $5k / website)
QUICK_INTL_NICHES = [
    "Roofing Contractors",
    "HVAC Services",
    "Plumbing Services",
    "Solar Panel Installation",
    "Home Remodeling",
    "Tree Service",
    "Auto Detailing",
    "Dental Clinic",
    "Med Spa",
    "Commercial Cleaning",
    "Pool Installation",
]

# Quick US and European cities
INTL_CITIES = [
    "Miami, FL",
    "New York, NY",
    "Los Angeles, CA",
    "Houston, TX",
    "Dallas, TX",
    "Chicago, IL",
    "London",
    "Berlin",
    "Warsaw",
    "Prague",
]

# High-ticket niches for US & Europe
US_EU_HIGH_TICKET_NICHES = [it for it in POPULAR_NICHES if it.get("category", "").startswith("🇺🇸/🇪🇺")]

# Major cities in Belarus for instant 1-click chips
BY_CITIES = [
    "Минск",
    "Брест",
    "Гродно",
    "Гомель",
    "Витебск",
    "Могилев",
    "Барановичи",
    "Бобруйск",
    "Пинск",
    "Борисов",
    "Солигорск",
]



