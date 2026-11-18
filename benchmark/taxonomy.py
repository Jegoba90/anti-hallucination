"""What a sentence can be, as benchmark/GUIA.md defines it: one place for the labeling page and the metrics."""

VERDICTS = ("correct", "neutral", "error")

# (id, name in the guide, group, what it is). Groups: "fact" says something false
# or absent; "added" claims what the data does not say; "other" is the rest.
TYPES: tuple[tuple[str, str, str, str], ...] = (
    ("wrong_figure", "Cifra equivocada", "fact", "Corresponde a un dato pero con otro valor, otra unidad u otra escala."),
    ("invented_figure", "Cifra inventada", "fact", "No corresponde a ningún dato ni fuente."),
    ("wrong_calculation", "Cálculo equivocado", "fact", "Una variación, total, promedio o proporción que el modelo calculó mal."),
    ("wrong_attribution", "Atribución equivocada", "fact", "Una cifra o un veredicto correctos, en otra métrica, entidad o período."),
    ("wrong_direction", "Dirección equivocada", "fact", "Subió por bajó o al revés, o una variación negativa sin signo ni palabra que lo diga."),
    ("invented_name", "Nombre inventado", "fact", "Una empresa, producto, persona, lugar o campaña que no está en los datos."),
    ("invented_fact", "Hecho inventado", "fact", "Un hecho sin cifras que no está en los datos ni en las fuentes."),
    ("contradicts_source", "Contradice una fuente", "fact", "Dice algo distinto de una fuente o le atribuye lo que no dice."),
    ("unsupported_cause", "Causa sin respaldo", "added", "Explica por qué pasó algo sin que los datos lo digan."),
    ("unsupported_forecast", "Predicción sin respaldo", "added", "Anticipa lo que va a pasar."),
    ("recommendation", "Recomendación", "added", "Recomienda una acción que los datos no piden."),
    ("unsupported_judgment", "Juicio sin respaldo", "added", "Califica, compara o da certeza sin respaldo."),
    ("other", "Otro", "other", "Otro error: describirlo en la nota."),
)
TYPE_IDS = tuple(ident for ident, _, _, _ in TYPES)
GROUP_OF = {ident: group for ident, _, group, _ in TYPES}
GROUPS = {"fact": "Errores de hecho", "added": "Agregados sin respaldo", "other": "Otros"}
