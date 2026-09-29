"""Work types, skills, equipment and request texts of the case, written as dispatchers do.

Work types and their norms are the organizer's «Нормативы.xlsx» (migration 0011). BK/HD
types and their shares follow the organizer's day files and the experts' guidance for own
synthetic data: 40% local repairs, 40% connections, 10% emergencies, 10% equipment orders.
"""

from dataclasses import dataclass

from app.modules.source_import.classify import SKILL_BY_CATEGORY


@dataclass(frozen=True, kw_only=True)
class WorkTypeSpec:
    code: str
    name: str
    category: str
    priority: int
    travel_minutes: int
    work_minutes: int
    documents_minutes: int
    bk_type: str
    share: float

    @property
    def skill(self) -> str:
        return SKILL_BY_CATEGORY[self.category]

    @property
    def service_minutes(self) -> int:
        """Time at the address: the planner adds the travel itself."""
        return self.work_minutes + self.documents_minutes


WORK_TYPES = (
    WorkTypeSpec(
        code="connection",
        name="Подключение клиентов Базовая",
        category="connection",
        priority=2,
        travel_minutes=20,
        work_minutes=60,
        documents_minutes=10,
        bk_type="Подключение",
        share=0.40,
    ),
    WorkTypeSpec(
        code="emergency",
        name="Аварий на ТКД",
        category="emergency",
        priority=1,
        travel_minutes=20,
        work_minutes=80,
        documents_minutes=0,
        bk_type="Глобальная проблема",
        share=0.10,
    ),
    WorkTypeSpec(
        code="additional",
        name="Дозаказ оборудования",
        category="additional",
        priority=3,
        travel_minutes=20,
        work_minutes=10,
        documents_minutes=10,
        bk_type="Дозаказ",
        share=0.10,
    ),
    WorkTypeSpec(
        code="repair",
        name="Локальная заявка/ремонт у клиента",
        category="repair",
        priority=3,
        travel_minutes=20,
        work_minutes=30,
        documents_minutes=0,
        bk_type="Локальная заявка",
        share=0.40,
    ),
)
WORK_TYPE_BY_CODE = {spec.code: spec for spec in WORK_TYPES}

# The three skills of the case decide eligibility; the rest describe the engineer.
CASE_SKILLS = ("Локальные работы", "Работы на подключение и дозаказы", "Аварийные работы")
EXTRA_SKILLS = (
    "Монтаж и сварка ВОЛС",
    "Настройка IPTV и видеонаблюдения",
    "Допуск по электробезопасности (III группа)",
)
SKILLS = CASE_SKILLS + EXTRA_SKILLS
assert set(CASE_SKILLS) == set(SKILL_BY_CATEGORY.values())


@dataclass(frozen=True, kw_only=True)
class ApplianceSpec:
    key: str
    name: str
    type: str
    unit: str
    description: str
    is_active: bool = True


APPLIANCES = (
    ApplianceSpec(
        key="router_giga",
        name="Wi-Fi роутер SmartBox GIGA",
        type="CLIENT_ROUTER",
        unit="шт",
        description="Двухдиапазонный роутер для тарифов до 1 Гбит/с, выдаётся при подключении",
    ),
    ApplianceSpec(
        key="router_pro",
        name="Wi-Fi роутер SmartBox Pro",
        type="CLIENT_ROUTER",
        unit="шт",
        description="Роутер Wi-Fi 6 для тарифов 500 Мбит/с и выше",
    ),
    ApplianceSpec(
        key="router_turbo",
        name="Wi-Fi роутер SmartBox Turbo+",
        type="CLIENT_ROUTER",
        unit="шт",
        description="Снят с выдачи новым абонентам, остатки используются для замены",
        is_active=False,
    ),
    ApplianceSpec(
        key="mesh",
        name="Wi-Fi Mesh-система (2 модуля)",
        type="CLIENT_ROUTER",
        unit="компл.",
        description="Дозаказ для больших квартир: два модуля с бесшовным роумингом",
    ),
    ApplianceSpec(
        key="ont",
        name="Оптический терминал ONT GPON ZTE F670",
        type="CLIENT_ROUTER",
        unit="шт",
        description="Абонентский терминал для домов с технологией GPON",
    ),
    ApplianceSpec(
        key="tv_box",
        name="ТВ-приставка Билайн ТВ 4K",
        type="TV_BOX",
        unit="шт",
        description="IPTV-приставка с пультом, дозаказ и замена у абонента",
    ),
    ApplianceSpec(
        key="speaker",
        name="Умная колонка с голосовым помощником",
        type="SPEAKER",
        unit="шт",
        description="Дозаказ по подписке, установка и привязка к аккаунту",
    ),
    ApplianceSpec(
        key="camera",
        name="IP-камера облачного видеонаблюдения",
        type="IP_CAMERA",
        unit="шт",
        description="Камера для квартиры или подъезда с записью в облако",
    ),
    ApplianceSpec(
        key="utp",
        name="Кабель UTP cat.5e 4×2×0,5",
        type="CABLE",
        unit="м",
        description="Абонентская разводка от этажного щита до квартиры",
    ),
    ApplianceSpec(
        key="patch_utp",
        name="Патч-корд UTP cat.5e, 3 м",
        type="CABLE",
        unit="шт",
        description="Подключение роутера и ТВ-приставки",
    ),
    ApplianceSpec(
        key="rj45",
        name="Коннектор RJ-45 cat.5e",
        type="CABLE",
        unit="шт",
        description="Обжим абонентского кабеля",
    ),
    ApplianceSpec(
        key="drop",
        name="Кабель оптический дроп, 1 волокно",
        type="FIBER",
        unit="м",
        description="Абонентская оптическая линия GPON",
    ),
    ApplianceSpec(
        key="patch_sc",
        name="Патч-корд оптический SC/APC–SC/APC, 3 м",
        type="FIBER",
        unit="шт",
        description="Коммутация на ТКД и у абонента",
    ),
    ApplianceSpec(
        key="sfp",
        name="SFP-модуль 1G, 1310 нм, 20 км",
        type="FIBER",
        unit="шт",
        description="Замена модуля магистрального порта коммутатора доступа",
    ),
    ApplianceSpec(
        key="splitter",
        name="Оптический делитель PLC 1×8",
        type="FIBER",
        unit="шт",
        description="Распределение GPON в слаботочном стояке",
    ),
    ApplianceSpec(
        key="closure",
        name="Муфта оптическая МТОК-К6",
        type="FIBER",
        unit="шт",
        description="Восстановление магистрального кабеля после обрыва",
    ),
    ApplianceSpec(
        key="switch24",
        name="Коммутатор доступа SNR-S2985G-24T",
        type="RACK_ROUTER",
        unit="шт",
        description="Замена коммутатора на ТКД",
    ),
    ApplianceSpec(
        key="switch8",
        name="Коммутатор доступа SNR-S2985G-8T",
        type="RACK_ROUTER",
        unit="шт",
        description="Малые ТКД в пяти- и девятиэтажных домах",
    ),
    ApplianceSpec(
        key="psu",
        name="Блок питания коммутатора 12 В, 5 А",
        type="OTHER",
        unit="шт",
        description="Замена блока питания на ТКД",
    ),
    ApplianceSpec(
        key="ups",
        name="ИБП для узла доступа 600 ВА",
        type="OTHER",
        unit="шт",
        description="Резервное питание ТКД",
    ),
    ApplianceSpec(
        key="lock",
        name="Замок антивандального шкафа ТКД",
        type="OTHER",
        unit="шт",
        description="Замена после вскрытия шкафа",
    ),
    ApplianceSpec(
        key="crimper",
        name="Кримпер для RJ-45",
        type="TOOL",
        unit="шт",
        description="Инструмент монтажника, выдаётся под подпись",
    ),
    ApplianceSpec(
        key="tester",
        name="Кабельный тестер UTP",
        type="TOOL",
        unit="шт",
        description="Проверка абонентской линии",
    ),
    ApplianceSpec(
        key="splicer",
        name="Сварочный аппарат для оптического волокна",
        type="TOOL",
        unit="шт",
        description="Выдаётся аварийным бригадам",
    ),
    ApplianceSpec(
        key="reflectometer",
        name="Оптический рефлектометр",
        type="TOOL",
        unit="шт",
        description="Поиск места обрыва ВОЛС",
    ),
)
APPLIANCE_BY_KEY = {spec.key: spec for spec in APPLIANCES}

# Each work type requires only what every visit of that type really needs.
REQUIRED_APPLIANCES = {"connection": (("router_giga", 1),)}
# The spare consumables every engineer of an office takes on top of the day's requests
# (T08 office_kit_reserves: the norm is topped up when the kit is issued).
KIT_RESERVES = (("rj45", 10), ("patch_utp", 2), ("patch_sc", 2))


@dataclass(frozen=True, kw_only=True)
class RequestKind:
    """One HelpDesk request type with its share inside the BK type and visit texts."""

    hd_type: str
    weight: int
    titles: tuple[str, ...]
    descriptions: tuple[str, ...]
    # Equipment taken for the visit: (appliance key, quantity range).
    appliances: tuple[tuple[str, int, int], ...] = ()


REQUEST_KINDS = {
    "connection": (
        RequestKind(
            hd_type="Конвергенция абонента",
            weight=70,
            titles=(
                "Подключение домашнего интернета к мобильному тарифу",
                "Конвергенция: интернет и ТВ для абонента мобильной связи",
                "Подключение по конвергентному тарифу",
            ),
            descriptions=(
                "Абонент мобильной связи подключает домашний интернет {speed} Мбит/с. "
                "Проложить кабель от этажного щита до квартиры (около {meters} м), "
                "установить и настроить роутер, показать клиенту приложение.",
                "Конвергентный тариф: интернет {speed} Мбит/с и ТВ. Установить роутер и "
                "ТВ-приставку, кабель завести в комнату у окна, около {meters} м.",
                "Подключение по заявке из салона связи. Интернет {speed} Мбит/с, "
                "клиент просит аккуратную прокладку в кабель-канале.",
            ),
            appliances=(("utp", 10, 25), ("rj45", 2, 4), ("patch_utp", 1, 1)),
        ),
        RequestKind(
            hd_type="Заявка на подключение",
            weight=15,
            titles=("Новое подключение FTTB", "Подключение домашнего интернета"),
            descriptions=(
                "Новое подключение по FTTB, тариф {speed} Мбит/с. Дом подключён, свободный "
                "порт на ТКД есть. Нужна прокладка кабеля около {meters} м.",
                "Клиент переехал в квартиру, ранее услуг не было. Подключить интернет "
                "{speed} Мбит/с, роутер в аренду.",
            ),
            appliances=(("utp", 10, 30), ("rj45", 2, 4), ("patch_utp", 1, 1)),
        ),
        RequestKind(
            hd_type="Заказ подключения/Дозаказ оборудования",
            weight=15,
            titles=("Подключение с дозаказом ТВ-приставки", "Подключение и установка приставки"),
            descriptions=(
                "Подключение интернета {speed} Мбит/с и установка ТВ-приставки 4K. "
                "Кабель до ТВ в гостиной, около {meters} м.",
                "Клиент заказал интернет и приставку. Установить оборудование, "
                "проверить каналы и скорость.",
            ),
            appliances=(("utp", 12, 30), ("rj45", 2, 6), ("patch_utp", 2, 2), ("tv_box", 1, 1)),
        ),
    ),
    "repair": (
        RequestKind(
            hd_type="Нет линка",
            weight=34,
            titles=("Нет линка", "Нет интернета: нет линка на порту", "Пропал интернет"),
            descriptions=(
                "Нет линка на порту коммутатора, на роутере не горит WAN. Клиент "
                "перезагружал роутер — без результата. Проверить кабель в квартире и "
                "на этажном щите.",
                "С утра нет интернета, у соседей по стояку работает. Линк на порту "
                "отсутствует, вероятно повреждён кабель в квартире после ремонта.",
                "Интернет пропал после замены входной двери. Проверить абонентский "
                "кабель в дверном проёме.",
            ),
            appliances=(("utp", 0, 15), ("rj45", 2, 2)),
        ),
        RequestKind(
            hd_type="Работа с кабелем",
            weight=8,
            titles=("Перенос кабеля и розетки", "Работа с кабелем в квартире"),
            descriptions=(
                "После ремонта клиент просит перенести интернет-розетку в другую комнату, "
                "около {meters} м кабеля в кабель-канале.",
                "Кабель перебит мебелью. Заменить участок кабеля от щита до роутера.",
            ),
            appliances=(("utp", 8, 25), ("rj45", 2, 2)),
        ),
        RequestKind(
            hd_type="Разрывы",
            weight=8,
            titles=("Разрывы соединения", "Интернет пропадает несколько раз в час"),
            descriptions=(
                "Соединение пропадает 5–10 раз в час, на порту частые падения линка. "
                "Проверить обжим коннектора и целостность кабеля.",
                "Разрывы по вечерам, по Wi-Fi и по кабелю. Проверить линию и роутер.",
            ),
            appliances=(("rj45", 2, 2),),
        ),
        RequestKind(
            hd_type="Низкая скорость",
            weight=8,
            titles=("Низкая скорость", "Скорость ниже тарифа"),
            descriptions=(
                "По тарифу {speed} Мбит/с, по замеру клиента по кабелю 40–60 Мбит/с. "
                "Проверить согласование порта, кабель и роутер.",
                "Низкая скорость по Wi-Fi в дальней комнате. Проверить роутер, "
                "предложить Mesh-систему.",
            ),
        ),
        RequestKind(
            hd_type="Рост ошибок на порту",
            weight=7,
            titles=("Рост ошибок на порту", "Ошибки CRC на порту абонента"),
            descriptions=(
                "Мониторинг: рост CRC-ошибок на порту доступа абонента. Переобжать "
                "кабель, при необходимости заменить патч-корд на щите.",
            ),
            appliances=(("rj45", 2, 2), ("patch_utp", 1, 1)),
        ),
        RequestKind(
            hd_type="IP-адрес 169...",
            weight=7,
            titles=("Роутер получает адрес 169.254.x.x", "Не выдаётся IP-адрес"),
            descriptions=(
                "Роутер получает адрес 169.254.x.x, DHCP не отвечает. Удалённо сброс "
                "не помог. Проверить линию и настройки роутера на месте.",
            ),
        ),
        RequestKind(
            hd_type="Переключение на Гбит/с",
            weight=8,
            titles=("Переключение на 1 Гбит/с", "Переход на гигабитный тариф"),
            descriptions=(
                "Клиент перешёл на тариф 1 Гбит/с. Переобжать кабель по четырём парам, "
                "заменить роутер на гигабитный, проверить скорость.",
            ),
            appliances=(("router_giga", 1, 1), ("rj45", 2, 2)),
        ),
        RequestKind(
            hd_type="Роутер. Замена техническим специалистом",
            weight=8,
            titles=("Замена роутера", "Роутер не включается"),
            descriptions=(
                "Роутер не включается после скачка напряжения. Заменить на SmartBox, "
                "перенести имя и пароль Wi-Fi.",
                "Роутер перегревается и перезагружается. Заменить по гарантии.",
            ),
            appliances=(("router_giga", 1, 1),),
        ),
        RequestKind(
            hd_type="TVE/ENT. Замена приставки техником",
            weight=6,
            titles=("Замена ТВ-приставки", "ТВ-приставка не загружается"),
            descriptions=(
                "ТВ-приставка зависает на заставке, сброс не помогает. Заменить "
                "приставку и активировать.",
            ),
            appliances=(("tv_box", 1, 1),),
        ),
        RequestKind(
            hd_type="TVE/ENT. Другие ошибки",
            weight=3,
            titles=("Нет изображения на части каналов",),
            descriptions=(
                "На части каналов ошибка воспроизведения. Проверить приставку, "
                "кабель до роутера и настройки IPTV.",
            ),
        ),
        RequestKind(
            hd_type="Мониторинг",
            weight=3,
            titles=("Оборудование клиента недоступно по мониторингу",),
            descriptions=(
                "Роутер клиента недоступен более суток, клиент не отвечает на звонки. "
                "Согласовать визит и проверить линию на месте.",
            ),
        ),
    ),
    "additional": (
        RequestKind(
            hd_type="Дозаказ оборудования",
            weight=70,
            titles=(
                "Дозаказ: Mesh-система",
                "Дозаказ: ТВ-приставка",
                "Дозаказ: IP-камера",
                "Дозаказ: умная колонка",
            ),
            descriptions=(
                "Клиент заказал дополнительное оборудование. Доставить, установить и "
                "настроить, показать работу в приложении.",
                "Дозаказ по подписке: установить оборудование и привязать к аккаунту.",
            ),
        ),
        RequestKind(
            hd_type="Заказ подключения/Дозаказ оборудования",
            weight=20,
            titles=("Дозаказ ТВ-приставки для второй комнаты",),
            descriptions=("Вторая ТВ-приставка в спальню. Кабель от роутера около {meters} м.",),
            appliances=(("tv_box", 1, 1), ("utp", 5, 15), ("rj45", 2, 2)),
        ),
        RequestKind(
            hd_type="Конвергенция абонента",
            weight=10,
            titles=("Дозаказ Mesh-системы по конвергентному тарифу",),
            descriptions=("По конвергентному тарифу клиенту положен второй модуль Wi-Fi.",),
            appliances=(("mesh", 1, 1),),
        ),
    ),
}

# The ordered device of «Дозаказ оборудования» follows the title.
ORDERED_DEVICE = {
    "Дозаказ: Mesh-система": "mesh",
    "Дозаказ: ТВ-приставка": "tv_box",
    "Дозаказ: IP-камера": "camera",
    "Дозаказ: умная колонка": "speaker",
}

TKD_PLACES = (
    "на чердаке",
    "в подвале",
    "в слаботочном шкафу на последнем этаже",
    "в антивандальном шкафу на {floor} этаже",
)


@dataclass(frozen=True, kw_only=True)
class Incident:
    title: str
    description: str
    appliances: tuple[tuple[str, int, int], ...] = ()


INCIDENTS = (
    Incident(
        title="Авария на ТКД: коммутатор доступа недоступен",
        description=(
            "Мониторинг: коммутатор доступа недоступен с {time}. Без услуг {subscribers} "
            "абонентов дома, жалобы на линии поддержки. ТКД {place}, подъезд {entrance}. "
            "Проверить питание и магистральный линк."
        ),
        appliances=(("switch8", 1, 1), ("psu", 1, 1)),
    ),
    Incident(
        title="Авария на ТКД: отключение электропитания",
        description=(
            "На ТКД {place} (подъезд {entrance}) пропало электропитание, ИБП разряжен. "
            "Не работают интернет и ТВ у {subscribers} абонентов. Проверить автомат в щите "
            "и ИБП, при необходимости заменить блок питания коммутатора."
        ),
        appliances=(("psu", 1, 1), ("ups", 1, 1)),
    ),
    Incident(
        title="Авария: обрыв магистрального оптического кабеля",
        description=(
            "Потерян линк до узла агрегации с {time}. Вероятно, оптический кабель "
            "повреждён при земляных работах во дворе. Без связи {subscribers} абонентов. "
            "Нужна сварка ВОЛС: взять муфту, сварочный аппарат и рефлектометр."
        ),
        appliances=(("closure", 1, 1), ("patch_sc", 2, 4)),
    ),
    Incident(
        title="Авария: повреждение кабелей в слаботочном стояке",
        description=(
            "После протечки в подъезде {entrance} пропал линк у абонентов стояка "
            "({subscribers} квартир). Проверить кабели в этажных щитах и на ТКД {place}."
        ),
        appliances=(("utp", 30, 60), ("rj45", 10, 20)),
    ),
    Incident(
        title="Авария: затопление подвала, узел связи обесточен",
        description=(
            "Управляющая компания сообщила о затоплении подвала. ТКД обесточен, без связи "
            "{subscribers} абонентов. Выезд совместно с представителем УК, проверить "
            "оборудование на влагу."
        ),
        appliances=(("switch8", 1, 1), ("psu", 1, 1)),
    ),
    Incident(
        title="Авария на ТКД: вскрыт антивандальный шкаф",
        description=(
            "Вскрыт шкаф ТКД {place}, повреждены патч-корды. Без услуг {subscribers} "
            "абонентов. Восстановить коммутацию и заменить замок шкафа."
        ),
        appliances=(("lock", 1, 1), ("patch_utp", 4, 8)),
    ),
    Incident(
        title="Авария на ТКД: перегрев коммутатора",
        description=(
            "Коммутатор на ТКД {place} перезагружается, порт магистрали уходит в ошибки, "
            "в шкафу жарко. Проверить вентиляцию, при необходимости заменить коммутатор. "
            "Затронуто {subscribers} абонентов."
        ),
        appliances=(("switch24", 1, 1),),
    ),
    Incident(
        title="Авария: ошибки на магистральном порту ТКД",
        description=(
            "Мониторинг: массовые CRC-ошибки на аплинке коммутатора ТКД {place} с {time}, "
            "у {subscribers} абонентов разрывы и низкая скорость. Заменить SFP-модуль и "
            "оптический патч-корд."
        ),
        appliances=(("sfp", 1, 1), ("patch_sc", 1, 2)),
    ),
)

CANCEL_REASONS = (
    "Клиент отказался от подключения",
    "Клиент не открыл дверь, телефон недоступен",
    "Клиент перенёс визит на другую дату",
    "Проблема решена удалённо поддержкой",
    "Дубль заявки",
    "Нет технической возможности: в доме нет свободных портов на ТКД",
)

DISPATCHER_NOTES = (
    "Клиент просит позвонить за 30 минут до приезда.",
    "Домофон не работает — клиент встретит у подъезда.",
    "Въезд во двор через шлагбаум, клиент откроет по звонку.",
    "Клиент будет дома только после {hour}:00.",
    "В квартире собака, клиент закроет её в комнате.",
    "Подъезд на кодовом замке, код есть в карточке HelpDesk.",
    "Клиент просит бахилы и аккуратную прокладку кабеля.",
    "Повторное обращение: визит на прошлой неделе проблему не решил.",
)

WORKER_REPORTS = {
    "connection": (
        "Подключено: кабель {meters} м, роутер настроен. По кабелю {speed} Мбит/с.",
        "Подключено, клиенту показано приложение. Wi-Fi 5 ГГц — {wifi} Мбит/с.",
    ),
    "repair": (
        "Переобжат коннектор RJ-45 в квартире, линк поднялся, ошибок на порту нет.",
        "Заменён участок кабеля в дверном проёме, скорость по кабелю {speed} Мбит/с.",
        "Заменён патч-корд на этажном щите, разрывов нет.",
        "Заменён роутер, настройки Wi-Fi перенесены.",
    ),
    "additional": (
        "Оборудование установлено и привязано к аккаунту клиента.",
        "Mesh-система настроена, покрытие во всех комнатах.",
    ),
    "emergency": (
        "Заменён блок питания коммутатора, связь восстановлена.",
        "Сварено 4 волокна в муфте, линк до агрегации восстановлен.",
        "Коммутатор заменён, все абоненты в сети.",
        "Восстановлена коммутация на ТКД, замок шкафа заменён.",
    ),
}

FOREMAN_NOTES = (
    "Перед выездом проверить остаток роутеров в офисе.",
    "Согласовано с клиентом, выезд подтверждён.",
    "Заявка на контроле: клиент обращается повторно.",
)

SPEEDS = (100, 300, 500, 500, 1000)
