"""Synthetic data sets for the evaluation: what a team hands a model to write a report from.

Five domains (sales, SaaS, support, finance, crypto), half in Spanish and half
in English. Each set has its figures (some with the previous period and the
change computed by the package), sometimes a verdict decided by thresholds, the
period, and sometimes notes to summarize. Every company, person and figure is
invented. A fixed seed makes the same sets on any machine, so the files in
benchmark/datasets/ can be checked against this script.

    python -m benchmark.make_datasets           # writes benchmark/datasets/{pilot,main}/
    python -m benchmark.make_datasets --check   # exit 1 if the files differ from what it makes
"""

import argparse
import json
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from antihallucination.data import parse_data

HERE = Path(__file__).resolve().parent
DATASETS = HERE / "datasets"
DOMAINS = ("sales", "saas", "support", "finance", "crypto")
LOCALES = ("es", "en")
# split -> (seed, data sets per domain and locale, of which for development)
SPLITS: dict[str, tuple[int, int, int]] = {"pilot": (1, 2, 2), "main": (2, 10, 3)}

Json = dict[str, object]


@dataclass(frozen=True)
class Metric:
    """One figure a domain reports, in both languages.

    unit "MONEY" is the data set's currency. change says how it is compared
    with the previous period: "percent", "points" (a percentage, so in points),
    "difference", or "" (never compared).
    """

    es: str
    en: str
    label_es: str
    art_es: str  # with its article, for «variación del ticket promedio»
    label_en: str
    subject_es: tuple[str, ...]
    subject_en: tuple[str, ...]
    unit_es: str
    unit_en: str
    low: float
    high: float
    decimals: int
    change: str
    compact: bool = False


def _m(
    es: str,
    en: str,
    label_es: str,
    art_es: str,
    label_en: str,
    subject_es: Sequence[str],
    subject_en: Sequence[str],
    unit: tuple[str, str],
    span: tuple[float, float],
    decimals: int,
    change: str,
    compact: bool = False,
) -> Metric:
    return Metric(
        es, en, label_es, art_es, label_en, tuple(subject_es), tuple(subject_en), unit[0], unit[1], span[0], span[1],
        decimals, change, compact,
    )


PCT = ("%", "%")
MONEY = ("MONEY", "MONEY")
METRICS: dict[str, tuple[Metric, ...]] = {
    "sales": (
        _m("unidades_vendidas", "units_sold", "unidades vendidas", "las unidades vendidas", "units sold",
           ["ventas", "unidades"], ["sales", "units"], ("unidades", "units"), (800, 60000), 0, "percent"),
        _m("facturacion", "revenue", "facturación", "la facturación", "revenue",
           ["facturación", "ingresos"], ["revenue"], MONEY, (40000, 25e6), 0, "percent", compact=True),
        _m("ticket_promedio", "average_order", "ticket promedio", "el ticket promedio", "average order value",
           ["ticket"], ["order value", "average order"], MONEY, (12, 320), 2, "percent"),
        _m("clientes_nuevos", "new_customers", "clientes nuevos", "los clientes nuevos", "new customers",
           ["clientes"], ["customers"], ("clientes", "customers"), (20, 4000), 0, "percent"),
        _m("tasa_devoluciones", "return_rate", "tasa de devoluciones", "la tasa de devoluciones", "return rate",
           ["devoluciones"], ["returns", "return rate"], PCT, (1, 12), 1, "points"),
        _m("conversion_web", "web_conversion", "conversión web", "la conversión web", "web conversion rate",
           ["conversión"], ["conversion"], PCT, (0.8, 5), 1, "points"),
        _m("pedidos_online", "online_orders", "pedidos online", "los pedidos online", "online orders",
           ["pedidos"], ["orders"], ("pedidos", "orders"), (300, 90000), 0, "percent"),
    ),
    "saas": (
        _m("mrr", "mrr", "ingreso mensual recurrente (MRR)", "el ingreso mensual recurrente (MRR)",
           "monthly recurring revenue (MRR)", ["MRR", "ingreso recurrente"], ["MRR", "recurring revenue"],
           MONEY, (8000, 3e6), 0, "percent", compact=True),
        _m("churn", "churn", "churn mensual", "el churn mensual", "monthly churn",
           ["churn", "bajas"], ["churn"], PCT, (0.5, 6), 1, "points"),
        _m("clientes_nuevos", "new_customers", "clientes nuevos", "los clientes nuevos", "new customers",
           ["clientes"], ["customers"], ("clientes", "customers"), (5, 600), 0, "percent"),
        _m("nrr", "nrr", "retención neta de ingresos (NRR)", "la retención neta de ingresos (NRR)",
           "net revenue retention (NRR)", ["NRR", "retención"], ["NRR", "retention"], PCT, (85, 130), 0, "points"),
        _m("conversion_prueba", "trial_conversion", "conversión de prueba a pago", "la conversión de prueba a pago",
           "trial-to-paid conversion", ["conversión"], ["conversion"], PCT, (4, 30), 1, "points"),
        _m("cac", "cac", "costo de adquisición de clientes (CAC)", "el costo de adquisición de clientes (CAC)",
           "customer acquisition cost (CAC)", ["CAC", "adquisición"], ["CAC", "acquisition cost"],
           MONEY, (40, 2500), 0, "percent"),
        _m("usuarios_activos", "active_users", "usuarios activos", "los usuarios activos", "active users",
           ["usuarios"], ["users", "active users"], ("usuarios", "users"), (300, 250000), 0, "percent"),
    ),
    "support": (
        _m("tickets_recibidos", "tickets_received", "tickets recibidos", "los tickets recibidos", "tickets received",
           ["tickets recibidos", "recibidos"], ["tickets received", "received"], ("tickets", "tickets"),
           (120, 25000), 0, "percent"),
        _m("tickets_resueltos", "tickets_resolved", "tickets resueltos", "los tickets resueltos", "tickets resolved",
           ["tickets resueltos", "resueltos"], ["tickets resolved", "resolved"], ("tickets", "tickets"),
           (100, 24000), 0, "percent"),
        _m("primera_respuesta", "first_response", "tiempo de primera respuesta", "el tiempo de primera respuesta",
           "first response time", ["primera respuesta", "tiempo de respuesta"], ["first response", "response time"],
           ("h", "h"), (0.4, 20), 1, "percent"),
        _m("tiempo_resolucion", "resolution_time", "tiempo medio de resolución", "el tiempo medio de resolución",
           "average resolution time", ["resolución"], ["resolution"], ("h", "h"), (2, 90), 1, "percent"),
        _m("csat", "csat", "satisfacción del cliente (CSAT)", "la satisfacción del cliente (CSAT)",
           "customer satisfaction (CSAT)", ["satisfacción", "CSAT"], ["satisfaction", "CSAT"], PCT, (68, 98), 0, "points"),
        _m("pendientes", "backlog", "tickets pendientes", "los tickets pendientes", "open backlog",
           ["pendientes", "backlog"], ["backlog"], ("tickets", "tickets"), (10, 3000), 0, "percent"),
        _m("escalamientos", "escalations", "escalamientos", "los escalamientos", "escalations",
           ["escalamientos"], ["escalations"], ("", ""), (1, 250), 0, "percent"),
    ),
    "finance": (
        _m("ingresos", "revenue", "ingresos", "los ingresos", "revenue",
           ["ingresos"], ["revenue"], MONEY, (2e6, 6e9), 0, "percent", compact=True),
        _m("margen_operativo", "operating_margin", "margen operativo", "el margen operativo", "operating margin",
           ["margen"], ["margin"], PCT, (-5, 35), 1, "points"),
        _m("resultado_neto", "net_income", "resultado neto", "el resultado neto", "net income",
           ["resultado neto", "ganancia"], ["net income", "profit"], MONEY, (-80e6, 600e6), 0, "difference",
           compact=True),
        _m("deuda_neta", "net_debt", "deuda neta", "la deuda neta", "net debt",
           ["deuda"], ["debt"], MONEY, (5e6, 4e9), 0, "percent", compact=True),
        _m("caja", "cash", "caja y equivalentes", "la caja y equivalentes", "cash and equivalents",
           ["caja"], ["cash"], MONEY, (1e6, 3e9), 0, "percent", compact=True),
        _m("empleados", "employees", "empleados", "los empleados", "employees",
           ["empleados", "plantilla"], ["employees", "headcount"], ("empleados", "employees"), (40, 30000), 0, "percent"),
        _m("ebitda", "ebitda", "EBITDA", "el EBITDA", "EBITDA",
           ["EBITDA"], ["EBITDA"], MONEY, (5e5, 2e9), 0, "percent", compact=True),
    ),
    "crypto": (
        _m("precio_btc", "btc_price", "precio de bitcoin (BTC)", "el precio de bitcoin (BTC)", "bitcoin (BTC) price",
           ["bitcoin", "BTC"], ["bitcoin", "BTC"], ("USD", "USD"), (25000, 160000), 0, "percent"),
        _m("precio_eth", "eth_price", "precio de ether (ETH)", "el precio de ether (ETH)", "ether (ETH) price",
           ["ether", "ETH"], ["ether", "ETH"], ("USD", "USD"), (900, 9000), 0, "percent"),
        _m("volumen_24h", "volume_24h", "volumen operado en 24 horas", "el volumen operado en 24 horas",
           "24-hour trading volume", ["volumen"], ["volume"], ("USD", "USD"), (8e9, 150e9), 0, "percent",
           compact=True),
        _m("dominancia_btc", "btc_dominance", "dominancia de bitcoin", "la dominancia de bitcoin", "bitcoin dominance",
           ["dominancia"], ["dominance"], PCT, (38, 68), 1, "points"),
        _m("tasa_financiamiento", "funding_rate", "tasa de financiamiento promedio",
           "la tasa de financiamiento promedio", "average funding rate", ["financiamiento"], ["funding"],
           PCT, (-0.02, 0.06), 3, "points"),
        _m("interes_abierto", "open_interest", "interés abierto en futuros", "el interés abierto en futuros",
           "futures open interest", ["interés abierto"], ["open interest"], ("USD", "USD"), (5e9, 90e9), 0,
           "percent", compact=True),
        _m("indice_miedo", "fear_greed", "índice de miedo y codicia", "el índice de miedo y codicia",
           "fear and greed index", ["miedo", "codicia", "sentimiento"], ["fear", "greed", "sentiment"],
           ("", ""), (5, 95), 0, "difference"),
    ),
}

COMPANIES = {
    "es": ("Nubra", "Tallo", "Brisa Market", "Quillon", "Corvina Labs", "Lumbre", "Arkadia", "Ventisca", "Mirlo",
           "Pampa Digital", "Cardón", "Alerce Foods"),
    "en": ("Kestrel Goods", "Harbor & Pine", "Bluefen", "Quarrow", "Lanternly", "Copperline", "Fenwick Data",
           "Tidewell", "Orbitly", "Marlow Supply", "Brightloom", "Ashgrove"),
}
NEWSLETTERS = {
    "es": ("Boletín Cripto Sur", "Mesa Pampa Trading", "Informe Andino de Mercados"),
    "en": ("Ledger Notes", "Blockwise Weekly", "Satstack Desk"),
}
CITIES = {
    "es": ("Córdoba", "Rosario", "Mendoza", "Montevideo", "Valparaíso", "Guadalajara", "Valencia", "Medellín",
           "Asunción", "Salta"),
    "en": ("Leeds", "Austin", "Denver", "Bristol", "Calgary", "Dublin", "Portland", "Glasgow", "Tampa", "Adelaide"),
}
PEOPLE = {
    "es": ("Lucía Ferrante", "Martín Ocampo", "Valeria Quiroga", "Diego Arrieta", "Carla Benítez"),
    "en": ("Hannah Pryce", "Marcus Bell", "Olivia Grant", "Samuel Ortiz", "Priya Nair"),
}
CAMPAIGNS = {"es": ("Primavera 360", "Vuelta al Cole", "Semana Naranja", "Días Calientes"),
             "en": ("Spring Reset", "Back to Basics", "Orange Week", "Summer Rush")}
CARRIERS = {"es": ("Ruta Veloz", "Envíos Delta"), "en": ("Swiftway", "Parcelon")}
CLIENTS = {"es": ("Grupo Taray", "Clínicas Moreno", "Logística Austral"),
           "en": ("Halden Health", "Pierce Logistics", "Avalon Schools")}
EXCHANGES = ("Orbita", "Kalder", "Nimbex")
CHAINS = ("Lumen", "Telar")
CURRENCIES = {"es": ("USD", "EUR"), "en": ("USD", "EUR", "GBP")}
MONTHS = {
    "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
}
WEEKDAYS = {"es": ("lunes", "martes", "miércoles", "jueves", "viernes"),
            "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")}
PERIODS = {"sales": ("quarter", "month"), "saas": ("month",), "support": ("month", "week"),
           "finance": ("quarter",), "crypto": ("week", "day")}
PREVIOUS = {
    "es": {"quarter": ("el trimestre anterior", "del trimestre anterior"), "month": ("el mes anterior", "del mes anterior"),
           "week": ("la semana anterior", "de la semana anterior"), "day": ("el día anterior", "del día anterior")},
    "en": {"quarter": ("the previous quarter", ""), "month": ("the previous month", ""),
           "week": ("the previous week", ""), "day": ("the previous day", "")},
}
AUDIENCES = {
    "es": {"sales": ("el directorio", "el equipo comercial", "la gerencia"),
           "saas": ("los inversores", "el equipo directivo"),
           "support": ("el equipo de soporte", "la gerencia de operaciones"),
           "finance": ("los accionistas", "el directorio"),
           "crypto": ("los suscriptores", "los clientes de la mesa de trading")},
    "en": {"sales": ("the board", "the sales team", "management"),
           "saas": ("investors", "the leadership team"),
           "support": ("the support team", "the operations managers"),
           "finance": ("shareholders", "the board"),
           "crypto": ("the subscribers", "the trading desk clients")},
}
TOPICS = {
    "es": {"sales": "los resultados de ventas", "saas": "las métricas del negocio",
           "support": "el desempeño del área de soporte", "finance": "los resultados financieros",
           "crypto": "el mercado cripto"},
    "en": {"sales": "sales results", "saas": "business metrics", "support": "support performance",
           "finance": "financial results", "crypto": "the crypto market"},
}
VERDICTS = {
    ("es", False): ("caída fuerte", "caída leve", "estabilidad", "subida leve", "subida fuerte"),
    ("en", False): ("a sharp drop", "a mild drop", "stability", "mild growth", "strong growth"),
    ("es", True): ("tendencia bajista fuerte", "tendencia bajista", "movimiento lateral", "tendencia alcista",
                   "tendencia alcista fuerte"),
    ("en", True): ("a strong downtrend", "a downtrend", "sideways movement", "an uptrend", "a strong uptrend"),
}
BOUNDS = {"percent": (-10, -2, 2, 10), "points": (-2, -0.3, 0.3, 2), "difference": (-15, -5, 5, 15)}


def _de(article: str) -> str:
    """«de» before a Spanish article: «del ticket», «de la facturación»."""
    return "del " + article[3:] if article.startswith("el ") else "de " + article


def _value(rng: random.Random, metric: Metric) -> float | int:
    r = rng.random()
    # Skewed toward the low end where the range is wide and positive, as real figures are.
    x = metric.low + (metric.high - metric.low) * (r * r if metric.low > 0 else r)
    return _round(x, metric.decimals)


def _round(x: float, decimals: int) -> float | int:
    return int(round(x)) if decimals == 0 else round(x, decimals)


def _growth(rng: random.Random) -> float:
    r = rng.random()
    if r < 0.25:
        low, high = 0.002, 0.02
    elif r < 0.65:
        low, high = 0.02, 0.10
    elif r < 0.9:
        low, high = 0.10, 0.25
    else:
        low, high = 0.25, 0.6
    size = low + (high - low) * rng.random()
    return -size if rng.random() < 0.45 else size


def _previous(rng: random.Random, metric: Metric, value: float | int) -> float | int:
    """The previous period's figure: a believable move from it to this one."""
    step = 10.0 ** -metric.decimals
    if metric.change == "percent":
        before = _round(value / (1 + _growth(rng)), metric.decimals)
    elif metric.change == "points":
        move = (0.1 + 2.4 * rng.random()) * (metric.high - metric.low) / 30
        before = _round(value - (move if rng.random() < 0.55 else -move), metric.decimals)
        if metric.unit_es == "%" and metric.low >= 0:
            before = min(max(before, metric.low / 2), 100)
    else:  # a difference: a count or an amount that can cross zero
        scale = max(abs(value), (metric.high - metric.low) / 20)
        before = _round(value - scale * (0.05 + 0.35 * rng.random()) * (1 if rng.random() < 0.5 else -1),
                        metric.decimals)
        if metric.low >= 0:
            before = max(before, metric.low)
    if before == value:  # a move too small to see at this precision
        before = _round(value - step, metric.decimals)
    return before


def _change_label(locale: str, metric: Metric, previous: str, previous_de: str) -> str:
    if locale == "es":
        label = f"variación {_de(metric.art_es)} respecto {previous_de}"
        return label + (", en puntos" if metric.change == "points" else "")
    label = f"change in {metric.label_en} vs {previous}"
    return label + (", in percentage points" if metric.change == "points" else "")


def _period(rng: random.Random, locale: str, kind: str) -> str:
    months = MONTHS[locale]
    if kind == "quarter":
        quarter = rng.choice((1, 2, 3))
        return f"el {('primer', 'segundo', 'tercer')[quarter - 1]} trimestre de 2026" if locale == "es" else f"Q{quarter} 2026"
    if kind == "month":
        month = rng.choice(range(10))
        return f"{months[month]} de 2026" if locale == "es" else f"{months[month]} 2026"
    if kind == "week":
        month = rng.choice((9, 10))
        start = rng.choice(range(1, 23))
        if locale == "es":
            return f"la semana del {start} al {start + 6} de {months[month]} de 2026"
        return f"the week of {months[month]} {start}–{start + 6}, 2026"
    day = rng.choice(range(1, 17))
    return f"el {day} de noviembre de 2026" if locale == "es" else f"November {day}, 2026"


def _sources(rng: random.Random, domain: str, locale: str, company: str) -> list[Json]:
    """Notes a model may summarize: invented, each with a name or a figure to get right."""
    es = locale == "es"
    city, other = rng.sample(CITIES[locale], 2)
    month = rng.choice(MONTHS[locale][:10])
    day = rng.choice(range(2, 28))
    weekday, later = rng.sample(WEEKDAYS[locale], 2)
    n = rng.choice(range(3, 60))
    version = f"{rng.choice(range(2, 9))}.{rng.choice(range(0, 15))}.{rng.choice(range(0, 6))}"
    options: list[tuple[str, str, str]]
    if domain == "sales":
        campaign, carrier = rng.choice(CAMPAIGNS[locale]), rng.choice(CARRIERS[locale])
        pct = rng.choice((15, 20, 25, 30, 40))
        options = [
            ("Nota del equipo comercial", "Campaña de temporada",
             f"La campaña «{campaign}» empezó el {day} de {month} en {city} y {other}, con descuentos de hasta "
             f"{pct} % en la categoría hogar.") if es else
            ("Sales team note", "Seasonal campaign",
             f"The {campaign} campaign started on {month} {day} in {city} and {other}, with discounts of up to "
             f"{pct}% on home goods."),
            ("Informe de logística", "Demoras en entregas",
             f"Durante {rng.choice(range(2, 9))} días hubo demoras en las entregas a {city} por un problema con el "
             f"operador {carrier}.") if es else
            ("Logistics report", "Delivery delays",
             f"For {rng.choice(range(2, 9))} days, deliveries to {city} were delayed by a problem with the carrier "
             f"{carrier}."),
        ]
    elif domain == "saas":
        client = rng.choice(CLIENTS[locale])
        options = [
            ("Notas de la versión", f"Versión {version}",
             f"La versión {version}, publicada el {day} de {month}, sumó inicio de sesión único y un nuevo tablero "
             "de uso.") if es else
            ("Release notes", f"Version {version}",
             f"Version {version}, released on {month} {day}, added single sign-on and a new usage dashboard."),
            ("Nota de éxito del cliente", "Renovación",
             f"{client} renovó su contrato por {rng.choice((2, 3))} años y sumó {rng.choice(range(20, 400))} "
             "licencias.") if es else
            ("Customer success note", "Renewal",
             f"{client} renewed its contract for {rng.choice((2, 3))} years and added "
             f"{rng.choice(range(20, 400))} seats."),
        ]
    elif domain == "support":
        code = rng.choice((402, 409, 502, 504))
        options = [
            (f"Ticket {rng.choice(range(4000, 9999))}", "Falla el pago con tarjeta",
             f"Desde el {weekday}, {n} clientes de {city} reportan que el pago con tarjeta falla con el error {code}. "
             f"El equipo de pagos revirtió la versión {version} el {later} y las fallas se detuvieron.") if es else
            (f"Ticket {rng.choice(range(4000, 9999))}", "Card payments fail",
             f"Since {weekday}, {n} customers in {city} report that card payments fail with error {code}. "
             f"The payments team rolled back release {version} on {later} and the failures stopped."),
            (f"Ticket {rng.choice(range(4000, 9999))}", "Facturas con el impuesto equivocado",
             f"{rng.choice(range(2, 9))} clientes empresa de {city} recibieron facturas con el impuesto equivocado. "
             "Finanzas está emitiendo las facturas de nuevo.") if es else
            (f"Ticket {rng.choice(range(4000, 9999))}", "Invoices show the wrong tax",
             f"{rng.choice(range(2, 9))} business customers in {city} received invoices with the wrong tax. "
             "Finance is reissuing them."),
            (f"Ticket {rng.choice(range(4000, 9999))}", "La app no sincroniza",
             f"Usuarios de Android reportan que la app no sincroniza los pedidos desde la versión {version}. "
             f"Hay {n} reportes y el equipo móvil prepara un parche.") if es else
            (f"Ticket {rng.choice(range(4000, 9999))}", "The app does not sync",
             f"Android users report that the app has not synced orders since version {version}. "
             f"There are {n} reports and the mobile team is preparing a fix."),
            (f"Ticket {rng.choice(range(4000, 9999))}", "Correos demorados",
             f"Los correos de confirmación llegan con hasta {rng.choice(range(2, 13))} horas de demora porque el "
             "proveedor de envíos limitó el tráfico. Se pasó el tráfico a un proveedor alternativo.") if es else
            (f"Ticket {rng.choice(range(4000, 9999))}", "Delayed emails",
             f"Confirmation emails arrive up to {rng.choice(range(2, 13))} hours late because the email provider "
             "throttled sending. Traffic was moved to a backup provider."),
        ]
    elif domain == "finance":
        person = rng.choice(PEOPLE[locale])
        amount = rng.choice((40, 75, 120, 180, 250))
        year = rng.choice((2027, 2028))
        options = [
            ("Comunicado de prensa", "Nueva planta",
             f"{company} anunció una inversión de {amount} millones de USD en una planta en {city}, que empezará a "
             f"operar en {year}.") if es else
            ("Press release", "New plant",
             f"{company} announced a USD {amount} million investment in a plant in {city}, due to start operating "
             f"in {year}."),
            ("Declaraciones de la dirección", "Prioridades",
             f"{person}, directora financiera, dijo que el foco de los próximos trimestres será bajar la deuda y "
             "sostener el margen.") if es else
            ("Management remarks", "Priorities",
             f"{person}, the chief financial officer, said the focus for the coming quarters is to cut debt and hold "
             "the margin."),
        ]
    else:
        exchange, chain = rng.choice(EXCHANGES), rng.choice(CHAINS)
        options = [
            (f"{exchange} News", "Retiros suspendidos",
             f"El exchange {exchange} suspendió los retiros de ETH durante {rng.choice(range(2, 9))} horas el "
             f"{weekday} por mantenimiento.") if es else
            (f"{exchange} News", "Withdrawals paused",
             f"The {exchange} exchange paused ETH withdrawals for {rng.choice(range(2, 9))} hours on {weekday} for "
             "maintenance."),
            ("Agenda de redes", "Actualización de red",
             f"La red {chain} activará la actualización «Faro» el {day} de {month}.") if es else
            ("Network calendar", "Network upgrade",
             f"The {chain} network will activate the Beacon upgrade on {month} {day}."),
        ]
    count = 2 if domain == "support" else (1 if rng.random() < 0.7 else 2)
    chosen = rng.sample(options, min(count, len(options)))
    return [{"id": f"s{index + 1}", "name": name, "title": title, "text": text}
            for index, (name, title, text) in enumerate(chosen)]


SOURCE_ODDS = {"sales": 0.5, "saas": 0.4, "support": 1.0, "finance": 0.6, "crypto": 0.6}


def make_dataset(rng: random.Random, ident: str, split: str, domain: str, locale: str) -> Json:
    """One data set: the facts, labels and sources in the package's data format, and the brief for the model."""
    es = locale == "es"
    crypto = domain == "crypto"
    company = rng.choice(NEWSLETTERS[locale] if crypto else COMPANIES[locale])
    currency = rng.choice(CURRENCIES[locale])
    kind = rng.choice(PERIODS[domain])
    previous, previous_de = PREVIOUS[locale][kind]
    metrics = rng.sample(METRICS[domain], rng.choice((4, 5, 5, 6)))
    facts: list[Json] = []
    changes: list[tuple[str, Metric]] = []
    for metric in metrics:
        name = metric.es if es else metric.en
        unit = (metric.unit_es if es else metric.unit_en).replace("MONEY", currency)
        value = _value(rng, metric)
        label = metric.label_es if es else metric.label_en
        subject = list(metric.subject_es if es else metric.subject_en)
        fact: Json = {"name": name, "value": value, "unit": unit, "label": label, "subject": subject}
        if metric.decimals:
            fact["decimals"] = metric.decimals
        if metric.compact and abs(value) >= 1e6:
            fact["compact"] = True
        facts.append(fact)
        roll = rng.random()
        if not metric.change or roll >= 0.8:
            continue
        change_name = f"variacion_{name}" if es else f"{name}_change"
        change_label = _change_label(locale, metric, previous, previous_de)
        if roll < 0.65:  # the previous figure is given, and the package computes the change
            before = _previous(rng, metric, value)
            before_name = f"{name}_anterior" if es else f"{name}_previous"
            before_fact: Json = {**fact, "name": before_name, "value": before,
                                 "label": f"{label} en {previous}" if es else f"{label} in {previous}"}
            before_fact.pop("compact", None)
            if metric.compact and abs(before) >= 1e6:
                before_fact["compact"] = True
            facts.append(before_fact)
            compute = "percent_change" if metric.change == "percent" else "difference"
            computed: Json = {"name": change_name, "compute": compute, "from": before_name, "to": name,
                              "label": change_label, "decimals": 1 if compute == "percent_change" else metric.decimals}
            if metric.compact and abs(value - before) >= 1e6:
                computed["compact"] = True
            facts.append(computed)
        else:  # only the change is given, as a team often has it
            if metric.change == "percent":
                moved, change_unit = round(_growth(rng) * 100, 1), "%"
            elif metric.change == "points":
                moved, change_unit = round((0.1 + 2.4 * rng.random()) * (1 if rng.random() < 0.55 else -1), 1), "pp"
            else:
                moved, change_unit = round((metric.high - metric.low) * 0.2 * (rng.random() - 0.5)), unit
            given: Json = {"name": change_name, "value": moved or (0.1 if change_unit in ("%", "pp") else 1),
                           "unit": change_unit, "change": True, "label": change_label, "subject": subject}
            if change_unit in ("%", "pp"):
                given["decimals"] = 1
            elif metric.compact and abs(moved) >= 1e6:
                given["compact"] = True
            facts.append(given)
        changes.append((change_name, metric))

    labels: list[Json] = [{"name": "periodo" if es else "period", "text": _period(rng, locale, kind)}]
    # A verdict where thresholds read well: a percent change, points, or the index.
    judged = [(name, metric) for name, metric in changes if metric.change != "difference" or not metric.unit_es]
    if judged and rng.random() < 0.7:
        change_name, metric = rng.choice(judged)
        words = VERDICTS[(locale, crypto)]
        bounds = BOUNDS[metric.change]
        verdict_name = f"tendencia_{metric.es}" if es else f"{metric.en}_trend"
        labels.append({"name": verdict_name, "from": change_name,
                       "thresholds": [[bound, word] for bound, word in zip(bounds, words)], "otherwise": words[-1]})

    data: Json = {"locale": locale, "facts": facts, "labels": labels, "known_names": [company]}
    if rng.random() < SOURCE_ODDS[domain]:
        data["sources"] = _sources(rng, domain, locale, company)
    brief: Json = {
        "company": company,
        "audience": rng.choice(AUDIENCES[locale][domain]),
        "topic": TOPICS[locale][domain],
        "period": labels[0]["text"],
        "sentences": [5, 8],
    }
    return {"id": ident, "split": split, "domain": domain, "locale": locale, "brief": brief, "data": data}


def make_split(split: str) -> list[Json]:
    """Every data set of a split, the same on every machine.

    Domains and languages are balanced: per domain and language, `per_group`
    sets, the first `dev` of them for development in the main split.
    """
    seed, per_group, dev = SPLITS[split]
    rng = random.Random(seed)
    groups = [(domain, locale) for domain in DOMAINS for locale in LOCALES for _ in range(per_group)]
    rng.shuffle(groups)
    seen: dict[tuple[str, str], int] = {}
    sets: list[Json] = []
    width = len(str(len(groups)))
    for index, (domain, locale) in enumerate(groups, start=1):
        rank = seen.get((domain, locale), 0)
        seen[(domain, locale)] = rank + 1
        part = "pilot" if split == "pilot" else ("dev" if rank < dev else "test")
        ident = f"{split[0]}{index:0{width}d}"
        dataset = make_dataset(rng, ident, part, domain, locale)
        parse_data(_mapping(dataset["data"]))  # the package must read it as it is
        sets.append(dataset)
    return sets


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected an object")
    return {str(key): item for key, item in value.items()}


def describe_parts(dataset: Mapping[str, object]) -> dict[str, object]:
    """The data as the model and the people labeling see it, in parts.

    Every figure is written the way the package writes it, so the model, the
    people and the checks all read the same numbers.
    """
    data = _mapping(dataset["data"])
    brief = _mapping(dataset["brief"])
    locale = str(dataset["locale"])
    parsed = parse_data(data)
    facts = {fact.name: fact for fact in parsed.facts}
    labels = {label.name: label for label in parsed.labels}
    rows: list[list[str]] = []
    for raw in (_mapping(item) for item in _list(data.get("facts"))):
        fact = facts[str(raw["name"])]
        rows.append([f"{fact.label[:1].upper()}{fact.label[1:]}", fact.render(locale)])
    verdicts: list[list[str]] = []
    for raw in (_mapping(item) for item in _list(data.get("labels"))):
        if "from" in raw:
            verdicts.append([facts[str(raw["from"])].label, labels[str(raw["name"])].text])
    notes = [[str(note["id"]), str(note["name"]), str(note["title"]), str(note["text"])]
             for note in (_mapping(item) for item in _list(data.get("sources")))]
    return {"locale": locale, "company": str(brief["company"]), "period": str(brief["period"]),
            "facts": rows, "verdicts": verdicts, "notes": notes}


def describe(dataset: Mapping[str, object]) -> str:
    """The data as a block of text, for the model's prompt."""
    parts = describe_parts(dataset)
    es = parts["locale"] == "es"
    lines = [f"{'Empresa' if es else 'Company'}: {parts['company']}",
             f"{'Período' if es else 'Period'}: {parts['period']}", "", "Datos:" if es else "Data:"]
    lines += [f"- {label}: {value}" for label, value in _rows(parts["facts"])]
    lines += [f"- Veredicto sobre la {about}: {verdict}" if es else f"- Verdict on the {about}: {verdict}"
              for about, verdict in _rows(parts["verdicts"])]
    notes = _rows(parts["notes"])
    if notes:
        lines += ["", "Notas para el informe:" if es else "Notes for the report:"]
        quote = ("«", "»") if es else ("\"", "\"")
        lines += [f"[{ident}] {name}, {quote[0]}{title}{quote[1]}: {text}" for ident, name, title, text in notes]
    return "\n".join(lines)


def _rows(value: object) -> list[list[str]]:
    return [[str(cell) for cell in row] for row in value] if isinstance(value, list) else []


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def dataset_path(dataset: Mapping[str, object]) -> Path:
    split = "pilot" if dataset["split"] == "pilot" else "main"
    return DATASETS / split / f"{dataset['id']}.json"


def _serialized(dataset: Mapping[str, object]) -> str:
    return json.dumps(dataset, ensure_ascii=False, indent=2) + "\n"


def load_datasets(split: str) -> list[dict[str, object]]:
    """The data sets of a split as written in benchmark/datasets/, in id order."""
    folder = DATASETS / ("pilot" if split == "pilot" else "main")
    sets: list[dict[str, object]] = []
    for path in sorted(folder.glob("*.json")):
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        sets.append(dict(_mapping(raw)))
    return sets


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare with the files instead of writing them")
    args = parser.parse_args(argv)
    differ = 0
    for split in SPLITS:
        for dataset in make_split(split):
            path = dataset_path(dataset)
            text = _serialized(dataset)
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    differ += 1
                    print(f"differs: {path.relative_to(HERE.parent)}")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if args.check:
        print("the data sets match this script" if not differ else f"{differ} data sets differ")
        return 1 if differ else 0
    print(f"wrote the data sets to {DATASETS.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
