# Evaluación

Cuánto funciona la capa, medido: de las oraciones que un modelo escribe mal
a partir de los datos, cuántas atrapa `verify()`, y de las que escribe bien,
cuántas corta de más. La verdad la dan personas que etiquetan cada oración
con los datos a la vista, sin saber qué modelo la escribió ni qué decidió la
capa.

Nada de esta carpeta entra al paquete de PyPI.

## Estado

| Fase | Qué | Estado |
|---|---|---|
| 0. Piloto | Guía, 20 conjuntos de datos, 40 informes de 2 modelos, 273 oraciones | Informes generados; falta etiquetar |
| 1. Conjunto completo | 100 conjuntos (30 de desarrollo, 70 de prueba), informes de 3 modelos | 48 de 300 informes generados; la generación sigue con una cuenta de Groq propia de la evaluación. Se etiquetan después del piloto, con la guía corregida |
| 2. Evaluación | Métricas, alternativas (un modelo como juez), análisis de errores | `evaluate.py` listo para la capa y dos alternativas sin modelo |
| 3. Publicar | Números en el README del proyecto | Pendiente |

## Cómo está armada

| Archivo | Qué hace |
|---|---|
| [GUIA.md](GUIA.md) | La guía de etiquetado: veredictos, tipos de error y reglas para los casos dudosos |
| [make_datasets.py](make_datasets.py) | Los conjuntos de datos sintéticos, con semilla fija: `datasets/pilot/` y `datasets/main/` |
| [generate_texts.py](generate_texts.py) | Les pide los informes a los modelos, sin la capa: `texts/<fase>/<modelo>/<conjunto>.json` |
| [labeling_bundle.py](labeling_bundle.py) | Arma el paquete para la página de etiquetado: `labeling/<fase>.json`, y aparte, en `<fase>-keys.json`, qué modelo escribió cada informe |
| [labeling/index.html](labeling/index.html) | La página de etiquetado |
| [evaluate.py](evaluate.py) | Las métricas, con intervalos del 95 % y el acuerdo entre las dos personas |
| [taxonomy.py](taxonomy.py) | Los veredictos y tipos de error de la guía, para la página y las métricas |

### Los datos

Cinco rubros (ventas, SaaS, soporte, finanzas y cripto), mitad en español y
mitad en inglés, parejos en cada fase. Cada conjunto trae cifras con su
período anterior y la variación calculada por la capa, a veces un veredicto
decidido por umbrales, el período y, a veces, notas para resumir (tickets,
comunicados, noticias). **Todo es inventado**: empresas, personas, cifras y
noticias. `python -m benchmark.make_datasets --check` comprueba que los
archivos son los que da el script, y un test lo corre en cada versión de
Python del CI.

### Los informes

Cada modelo recibe el pedido y los datos con las cifras escritas como las
escribe la capa. A la mitad de los conjuntos se les pide además que usen solo
los datos (prompt estricto); a la otra mitad, no (prompt simple), como pide la
mayoría de la gente. Cada informe guarda el prompt, la respuesta, el modelo
que la sirvió y los tokens.

Modelos, todos en Groq el 2026-11-18: `openai/gpt-oss-120b` y
`qwen/qwen3.8-27b` en el piloto, más `openai/gpt-oss-20b` en la fase 1. Eran
los modelos de texto que Groq servía ese día.

### El etiquetado

Las oraciones se cortan con el mismo código que usa la capa, así que la
etiqueta *i* habla de la decisión *i* de `verify()`. La página muestra los
informes en un orden mezclado fijo, sin el modelo. Una parte de los informes
(un 25 % en el piloto) se marca para que la etiquete también una segunda
persona.

Mientras etiquetes, no abras `texts/` ni los archivos `-keys.json`: dicen qué
modelo escribió cada informe.

### Las métricas

`verify()` corre con los datos de cada informe y todos los controles
activados, como viene por defecto. Una oración etiquetada «error» es un
positivo; «correcta», un negativo; «neutral» se cuenta aparte, porque la capa
corta a propósito las oraciones sin datos. Se comparan tres sistemas sobre las
mismas oraciones: la capa, solo sus controles de cifras, y una regex ingenua
que marca toda oración con dígitos que no estén escritos en los datos.

## Para no engañarnos

- Las listas de palabras de la capa se ajustan solo con los conjuntos de
  desarrollo. Los de prueba se miran una vez, al final, con la capa congelada
  en un commit.
- Los errores sembrados a mano, cuando se sumen, se informan aparte de los
  naturales: inflan los números.
- Los números van con su intervalo y con ejemplos de lo que la capa no atrapa.

## Reproducir

```bash
python -m benchmark.make_datasets                      # los conjuntos de datos
python -m benchmark.generate_texts --split pilot \
  --model groq:openai/gpt-oss-120b --model groq:qwen/qwen3.8-27b
python -m benchmark.labeling_bundle --split pilot     # el paquete de la página
python -m benchmark.evaluate --split pilot            # con las etiquetas en labels/pilot.json
```

`generate_texts` lee la clave de `GROQ_API_KEY` o de `.tmp/eval.env`, que git
ignora. Usá una cuenta de Groq que no use nada en producción: los límites de
Groq son por cuenta, no por clave, y la generación los agota.
