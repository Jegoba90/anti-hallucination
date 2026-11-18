# Guía de etiquetado

Esta guía dice cómo etiquetar cada oración de los informes de la evaluación.
Las etiquetas son la verdad contra la que se mide la capa, así que tienen que
decir lo que piensa un lector atento con los datos a la vista, no lo que la
capa sabe revisar. Si una regla de esta guía te parece injusta para el lector,
anotalo: la guía se corrige después del piloto.

## Cómo se trabaja

- Cada informe lo escribió un modelo a partir de los datos que ves al lado.
  No sabés qué modelo fue, y no ves lo que decidió la capa: así tiene que ser.
- Leé primero los datos y el informe entero; después etiquetá oración por
  oración. Cada oración se juzga sola, con los datos y las fuentes.
- Una oración tiene un solo veredicto. Si tiene un error, marcá todos los
  tipos que veas.
- Si dudás, elegí lo que te parezca más probable y marcá **Dudosa**. Esas se
  revisan entre las dos personas.
- No busques la oración perfecta. La pregunta es una sola: ¿lo que afirma está
  en los datos o en las fuentes, o se deduce de ellos sin hacer cuentas?

## El veredicto

| Veredicto | Cuándo |
|---|---|
| **Correcta** | Todo lo que afirma está en los datos o en las fuentes, o se deduce de ellos sin cálculo. |
| **Neutral** | No afirma nada que se pueda verificar: anuncia el informe, saluda o une dos ideas («A continuación, el resumen del trimestre.»). Si opina sobre los resultados, no es neutral. |
| **Error** | Afirma al menos una cosa que los datos y las fuentes no respaldan, o que los contradice. |

Con **Correcta** hay una marca más: **Cifra calculada por el modelo**. Va
cuando la oración trae una cifra que no está en los datos pero que el modelo
calculó bien (un total, un promedio, una diferencia). La oración sigue siendo
correcta; la marca sirve para medir aparte esos casos.

## Los tipos de error

**Errores de hecho**: dicen algo falso o que no está.

| Tipo | Qué es | Ejemplo, con los datos «ventas: 1.250 unidades; variación: −3,2 %» |
|---|---|---|
| **Cifra equivocada** | Una cifra que corresponde a un dato pero con otro valor, otra unidad u otra escala. | «Las ventas fueron de 1.320 unidades.» «Cayeron 3,2 puntos.» |
| **Cifra inventada** | Una cifra que no corresponde a ningún dato ni fuente. | «El 40 % de las ventas fue online.» |
| **Cálculo equivocado** | Una cifra que el modelo calculó (variación, total, promedio, proporción) y está mal. | «Se perdieron 60 unidades respecto del trimestre anterior» (eran 41). |
| **Atribución equivocada** | Una cifra o un veredicto correctos, pero puestos en otra métrica, otra entidad u otro período. | «Los clientes nuevos fueron 1.250.» «En el segundo trimestre…» |
| **Dirección equivocada** | Dice que algo subió cuando bajó, o al revés, o que se mantuvo cuando cambió. También una variación negativa escrita sin el signo y sin una palabra que diga que bajó. | «Las ventas crecieron 3,2 %.» «La variación fue de 3,2 %.» |
| **Nombre inventado** | Un nombre propio (empresa, producto, persona, lugar, campaña) que no está en los datos ni en las fuentes. | «Gracias a la campaña Verano Plus…» (si nadie la nombra) |
| **Hecho inventado** | Un hecho sin cifras que no está en los datos ni en las fuentes. | «Los clientes elogiaron la nueva interfaz.» «Por segundo trimestre consecutivo…» |
| **Contradice una fuente** | Dice algo distinto de lo que dice una fuente, o le atribuye a una fuente algo que no dice. | La fuente dice «23 clientes» y la oración, «decenas de clientes en toda Europa». |

**Agregados sin respaldo**: no son necesariamente falsos, pero el informe los
afirma sin que los datos lo digan.

| Tipo | Qué es | Ejemplo |
|---|---|---|
| **Causa sin respaldo** | Explica por qué pasó algo («gracias a», «debido a», «impulsado por») sin que los datos o las fuentes lo digan. | «Las ventas cayeron por la suba de precios.» |
| **Predicción sin respaldo** | Anticipa lo que va a pasar. | «Las ventas seguirán bajando el próximo trimestre.» |
| **Recomendación** | Recomienda una acción que los datos no piden. | «Conviene reforzar la inversión en marketing.» |
| **Juicio sin respaldo** | Califica, compara o da certeza sin respaldo: «récord», «excelente», «preocupante», «por encima del promedio del sector», «sin duda». | «Fue un trimestre sólido.» |

Y **Otro**, para un error que no entra en ninguno: describilo en la nota.

## Reglas para los casos dudosos

1. **Redondeos.** Una cifra aproximada es correcta si el dato, redondeado a la
   precisión que se escribe, da esa cifra: «48 mil» o «casi 50 mil» por
   48.200 están bien; «45 mil» no. «3 %» por 3,2 % está bien; «4 %» no.
2. **Porcentajes y puntos.** Si el churn pasó de 2,7 % a 2,3 %, bajó
   0,4 *puntos*. «Bajó 0,4 %» es una **cifra equivocada** (otra unidad).
3. **Direcciones.** «Las ventas bajaron» con una variación negativa es
   correcta: se deduce sin cálculo. «Cayeron 3,2 %» también. «La variación fue
   de 3,2 %» con −3,2 % es **dirección equivocada**: el lector entiende que
   subió.
4. **Veredictos de los datos.** Los datos traen veredictos decididos por
   reglas («caída leve»). Repetirlos o decirlos con otras palabras del mismo
   grado («una leve baja») es correcto. Cambiarles el grado («una caída
   moderada», «un derrumbe») es **juicio sin respaldo**.
5. **El nombre de la empresa, el período y los nombres de las fuentes** están
   en los datos: mencionarlos es correcto.
6. **Calificativos suaves.** «Las ventas bajaron levemente» con −3,2 % y un
   veredicto «caída leve» es correcto. Sin un veredicto que lo diga, un
   calificativo de grado («levemente», «fuertemente», «notable») es **juicio
   sin respaldo**, salvo que sea evidente por la cifra (−0,1 % es leve).
7. **Cálculos correctos.** Si el modelo suma, resta o calcula una proporción y
   le da bien, la oración es **Correcta** con la marca **Cifra calculada por el
   modelo**. Si le da mal, es **Cálculo equivocado**.
8. **Fuentes.** Resumir una fuente con otras palabras es correcto si no cambia
   lo que dice: cifras, nombres, fechas y quién hizo qué.
9. **Una oración con dos afirmaciones**, una buena y una mala, es **Error**.
10. **Oraciones cortadas raro.** Las oraciones se cortan con el mismo código
    que usa la capa. Si un corte junta dos oraciones o parte una, etiquetá el
    pedazo como está y anotalo.

## Para la segunda persona

Etiquetá solo los informes marcados como «control de acuerdo», sin mirar las
etiquetas de nadie. Con esos se mide cuánto coinciden las dos personas. Si
coinciden poco, la guía está mal escrita, no ustedes.
