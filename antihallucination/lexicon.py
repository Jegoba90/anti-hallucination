"""The words the checks look for, in Spanish and English.

These lists are best effort: a model keeps finding new ways to say what it
cannot back, and a list only catches the phrasings it already holds. The checks
that do not depend on a list are the figures (each one is matched against a
fact or a source) and the placeholders (the writer never types a figure at
all). These lists cover the usual ways a text claims more than its data: a
direction, a forecast, a certainty or a cause.

Every pattern runs on casefolded text with its accents kept: «bajó» moved and
«bajo» did not.
"""

import re

# A move up or down. Words that are also adjectives or prepositions («baja»,
# «bajo», «alta», «lower band») are left out on purpose: they would turn a
# position into a move.
UP = re.compile(
    r"\b(?:"
    r"sub(?:e|en|i[oó]|ieron|ida|idas|ido|iendo)|crec(?:e|en|i[oó]|ieron|ido|imiento|imientos|iendo)"
    r"|aument(?:a|an|[oó]|aron|ado|os|ando|[aá]ndose)|increment(?:a|an|[oó]|aron|ado|os|ando|[aá]ndose)"
    r"|repunt(?:a|an|[oó]|aron|e|es)|trep(?:a|an|[oó]|aron)|duplic(?:a|an|[oó]|aron)"
    r"|triplic(?:a|an|[oó]|aron)|al\s+alza|alzas?|se\s+dispar(?:a|an|[oó]|aron)"
    r"|ris(?:e|es|ing)|rose|risen|increas(?:e|es|ed|ing)|gr(?:ew|ow|ows|owing|own|owth)"
    r"|climb(?:s|ed|ing)?|jump(?:s|ed|ing)?|surg(?:e|es|ed|ing)|soar(?:s|ed|ing)?"
    r"|rall(?:y|ied|ies|ying)|rebound(?:s|ed|ing)?|gain(?:s|ed|ing)?|doubl(?:e|es|ed|ing)"
    r"|tripl(?:e|es|ed|ing)|higher(?=\s+than\b)|up(?=\s+(?:by\b|\d))"
    r")\b"
)
DOWN = re.compile(
    r"\b(?:"
    r"baj(?:ó|aron|an|ando|ado|ada|adas)|a\s+la\s+baja|ca(?:e|en|y[oó]|yeron|[ií]do|[ií]da|[ií]das|yendo)"
    r"|descend(?:i[oó]|ieron|ido|iendo)|desciend(?:e|en)|descensos?"
    r"|dismin(?:uye|uyen|uy[oó]|uyeron|uido|uci[oó]n|uciones|uyendo)"
    r"|redu(?:ce|cen|jo|jeron|cci[oó]n|cciones|ciendo|ci[eé]ndose)|retroced(?:e|en|i[oó]|ieron|ido|iendo)|retrocesos?"
    r"|desplom(?:a|an|[oó]|aron|e|es)|merm(?:a|an|[oó]|aron|as)|contraj(?:o|eron)|contracci[oó]n"
    r"|hund(?:e|en|i[oó]|ieron)|perd(?:i[oó]|ieron)"
    r"|f(?:all|alls|ell|allen|alling)|decreas(?:e|es|ed|ing)|declin(?:e|es|ed|ing)"
    r"|drop(?:s|ped|ping)?|dip(?:s|ped|ping)?|shr(?:ank|ink|inks|unk|inking)|slid(?:e|es|ing)?"
    r"|slump(?:s|ed|ing)?|plung(?:e|es|ed|ing)|tumbl(?:e|es|ed|ing)|sank|los(?:e|es|t|ing)"
    r"|halv(?:e|es|ed|ing)|contract(?:ed|ing|ion)|reduc(?:e|es|ed|ing|tion)"
    r"|lower(?=\s+than\b)|down(?=\s+(?:by\b|\d))"
    r")\b"
)
# Words that carry a minus sign the figure left out: «una pérdida de 120.000».
NEGATIVE_NOUNS = re.compile(
    r"\b(?:p[ée]rdidas?|d[ée]ficit|negativ[oa]s?|n[úu]meros\s+rojos|loss(?:es)?|deficit|negative"
    r"|shortfall|in\s+the\s+red)\b"
)
# What turns «subieron» into «no subieron». «no solo» / «not only» do not.
NEGATORS = frozenset(
    {
        "no", "sin", "ni", "nunca", "tampoco", "jamás", "jamas", "not", "never", "without", "neither",
        "nor", "didn't", "doesn't", "don't", "hasn't", "haven't", "wasn't", "weren't", "isn't",
        "aren't", "won't", "cannot", "can't", "didn’t", "doesn’t", "don’t", "hasn’t", "haven’t",
        "wasn’t", "weren’t", "isn’t", "aren’t", "won’t", "can’t",
    }
)  # fmt: skip
NOT_A_NEGATION = frozenset({"solo", "sólo", "solamente", "only"})

FORECAST = re.compile(
    r"\b(?:"
    r"podr[ií]an?|deber[ií]an?|se\s+esperan?|es\s+(?:muy\s+)?probable|probablemente|previsiblemente"
    r"|anticipan?|pron[oó]stic\w*|inminentes?|en\s+el\s+futuro|a\s+futuro"
    r"|pr[oó]xim[oa]s?\s+(?:d[ií]as?|semanas?|mes(?:es)?|trimestres?|a[ñn]os?|sesi[oó]n|sesiones|per[ií]odos?)"
    r"|van?\s+a\s+(?:subir|bajar|crecer|caer|aumentar|disminuir|seguir|continuar|mantenerse|recuperarse|repuntar)"
    # The synthetic future: «subirá», «será», «crecerán»; irregular ones listed.
    r"|\w+(?:ar|er|ir)án?|(?:habr|tendr|podr|saldr|har|dir|pondr|vendr|querr|sabr|valdr)án?"
    r"|will|won['’]t|would\s+likely|(?:is|are)\s+(?:expected|likely|projected|forecast|poised|set)\s+to"
    r"|likely\s+to|probably|forecasts?|forecasted|going\s+to"
    r"|next\s+(?:week|month|quarter|year|session|days?)s?"
    r"|in\s+the\s+(?:coming|next)\s+(?:days?|weeks?|months?|quarters?|years?)"
    r"|(?:should|could|may|might)\s+(?:rise|fall|grow|increase|decrease|decline|continue|remain|reach|recover|drop|climb|see)"
    r")\b"
)
CERTAINTY = re.compile(
    r"\b(?:"
    r"claramente|definitivamente|sin\s+lugar\s+a\s+dudas?|indudablemente|evidentemente|obviamente"
    r"|sin\s+duda(?:\s+alguna)?|inequ[ií]vocamente|categ[oó]ricamente|incuestionablemente|innegablemente"
    r"|con\s+(?:toda\s+)?certeza|con\s+toda\s+seguridad|de\s+manera\s+contundente|garantizad[oa]s?"
    r"|clearly|definitely|undoubtedly|obviously|certainly|unquestionably|undeniably"
    r"|without\s+(?:a|any)\s+doubt|no\s+doubt|beyond\s+(?:any\s+)?doubt|guaranteed?|for\s+sure"
    r")\b"
)
CAUSE = re.compile(
    r"\b(?:"
    r"debido\s+a|se\s+deb(?:e|en|i[oó]|ieron)\s+a|a\s+causa\s+de|gracias\s+a|por\s+culpa\s+de"
    r"|a\s+ra[ií]z\s+de|(?:provocad|causad|impulsad|motivad|originad|explicad|generad)[oa]s?\s+por"
    r"|lo\s+(?:que|cual)\s+(?:refleja|indica|demuestra|sugiere|evidencia|confirma|explica|implica|significa)"
    r"|(?:esto|ello|eso)\s+(?:refleja|indica|demuestra|sugiere|explica|implica|significa)"
    r"|por\s+lo\s+tanto|por\s+ende|en\s+consecuencia|como\s+(?:resultado|consecuencia)"
    r"|atribu(?:ye|yen|y[oó]|ido|ida|idos|idas|ible|ibles)"
    r"|because|due\s+to|owing\s+to|driven\s+by|caused\s+by|fuell?ed\s+by|thanks\s+to|as\s+a\s+result"
    r"|(?:which|this|that)\s+(?:reflects|indicates|shows|suggests|demonstrates|means|implies|signals)"
    r"|therefore|consequently|hence|led\s+to|resulted\s+in|attribut(?:ed|able)\s+to|on\s+the\s+back\s+of"
    r")\b"
)

# Capitalized words that name no one: months, weekdays and generic acronyms.
# Folded (casefolded, no accents).
NOT_NAMES = frozenset(
    {
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
        "setiembre", "octubre", "noviembre", "diciembre", "january", "february", "march", "april",
        "may", "june", "july", "august", "september", "october", "november", "december", "lunes",
        "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "monday", "tuesday",
        "wednesday", "thursday", "friday", "saturday", "sunday", "i",
        "usd", "eur", "gbp", "jpy", "cny", "chf", "cad", "aud", "mxn", "ars", "brl", "clp", "cop",
        "pen", "uyu", "kpi", "kpis", "ceo", "cfo", "coo", "cto", "pib", "gdp", "iva", "vat", "yoy",
        "mom", "qoq", "ytd", "ia", "ai", "id", "ok", "pdf", "url", "api", "utc",
    }
)  # fmt: skip
