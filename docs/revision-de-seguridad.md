# Revisión de seguridad

Revisión hecha el 2026-11-16, antes de publicar la 0.3.0, y sus arreglos, del
2026-11-17. Cubre la librería, el comando, el servidor MCP, el servicio HTTP
que trae la 0.3.0, su imagen Docker y los workflows de GitHub. El detalle de
cada arreglo, con sus mediciones, está en el
[registro de pruebas](pruebas-2026-11-16.md).

## Resultado

No se encontró nada que permita leer datos ajenos, ejecutar código o saltear el
token. Los hallazgos son de disponibilidad (un pedido chico que hace trabajar
mucho al servicio) y de endurecimiento. Están todos arreglados: el 1 salió con
la 0.2.2, y el resto sale con la 0.3.0.

| Punto | Qué pasaba | Afectaba | Arreglado en |
|---|---|---|---|
| 1. Textos largos | Una oración larga sin puntuación tardaba el cuadrado de su largo: 32 KB, 22 s | Librería, comando y MCP, hasta la 0.2.1 | 0.2.2 |
| 1b. Texto y datos grandes a la vez | Cada cifra contra cada fact: 64 KB, 15 s; un pedido de 16 KB daba un recibo de 135 MB | Quien controla también los datos: el servicio o un modelo por MCP | 0.3.0 |
| 2. Números con un exponente enorme | Un pedido de 64 bytes con `1e-10000000` recibía 10 MB; más de 28 dígitos se redondeaban | El servicio; la precisión, también la librería | 0.3.0 |
| 3. 500 en lugar de 400 | Un JSON muy anidado y una cifra enorme al redondear daban error del servidor | El servicio | 0.3.0 |
| 4. Vulnerabilidades en la imagen | 8 en paquetes de Python que trae pip y 220 en Debian, 2 con arreglo | La imagen | 0.3.0 |
| 5. Endurecimiento | Sin aviso sobre TLS; rutas REST locales abiertas a páginas web; acciones por tag | El servicio y el workflow de publicación | 0.3.0 |

## 1. Textos largos

Varias partes de la revisión de un texto volvían a leer la oración entera por
cada palabra, y una por cada palabra y cada cifra. Con una sola oración larga,
el tiempo crecía con el cuadrado del largo, y en un caso con el cubo. Ahora
cada oración se lee una vez. Las decisiones no cambiaron: el código nuevo dio
el mismo recibo que el anterior en 19.000 documentos al azar. 256 KB de
cualquiera de las formas medidas tardan como mucho 2,5 s.

Registro: «Textos largos que tardaban minutos» y «La versión 0.2.2».

## 1b. Texto y datos grandes a la vez

Arreglado el largo, quedaba lo que crece con el texto multiplicado por los
datos. Ahora cada cifra mira solo los facts a los que puede redondear, y cada
nombre o sujeto se busca solo donde puede estar. Un tope de 200.000
coincidencias rechaza el texto que coincide con los datos una y otra vez
(`TooManyMatches`, 413 en el servicio). Y el servicio corre cada pedido en un
proceso aparte, con 10 s y 1024 MB como máximo.

Registro: «Texto y datos grandes a la vez».

## 2. Números con un exponente enorme

El servicio lee los números del JSON como decimales exactos, y el recibo los
escribe completos. Un valor de 64 bytes como `1e-10000000` se escribía con diez
millones de dígitos. Ahora un valor tiene como máximo 40 dígitos escrito
entero, y uno más largo da 400. Al buscarlo apareció que un valor de más de 28
dígitos se redondeaba en el contexto decimal de Python: fallaba al escribirse,
o una cifra que difería del fact después del dígito 28 pasaba como buena.
Ahora se escribe y se compara sin redondear.

Registro: «Números con un exponente enorme».

## 3. 500 en lugar de 400

Un JSON anidado más allá de lo que Python puede leer daba 500; ahora da 400.
La cifra enorme que fallaba al redondearse ya no llega, por el límite del
punto 2.

Registro: «El servicio, endurecido».

## 4. Vulnerabilidades en la imagen

Las 8 de Python estaban en los paquetes que pip trae adentro (urllib3, msgpack
y el `pkg_resources` de setuptools); el servicio no usa pip y ahora se
desinstala. La imagen también instala los arreglos de Debian publicados
después de su base, y se construye de nuevo en cada release. Trivy: Python, de
8 a 0; Debian, de 220 a 218, ninguna con arreglo publicado.

Registro: «Vulnerabilidades conocidas en la imagen».

## 5. Endurecimiento

- El README dice que el servicio habla HTTP plano y que va detrás de un proxy
  con TLS o en una red privada, y sugiere `openssl rand -hex 32` para el token.
- Las rutas REST exigen `Content-Type: application/json` y, en un servicio
  local, un `Host` y un `Origin` locales, como ya hacía `/mcp`. Así una página
  web no puede usar el navegador de quien la visita para llegar al servicio.
- Las acciones de terceros en `publish.yml`, que corren con permiso para
  publicar, van fijadas por commit.

Registro: «El servicio, endurecido».

## Revisado, sin hallazgos

- El token: no se puede saltear por ruta, método ni websocket, ni por las rutas
  propias del SDK de MCP, y se compara en tiempo constante.
- Los logs no guardan el token ni los informes.
- Inyección y deserialización: el JSON se lee como datos, nunca como código.
- SSRF y gasto de claves: el servicio no llama a ningún modelo ni a ninguna URL.
- El replay de recibos, los workflows y el Dockerfile (Trivy `config`, sin
  hallazgos).
- Gitleaks: sin secretos en el historial ni en los archivos.

## Lo que queda

- **Debian.** Las 218 vulnerabilidades sin arreglo están en paquetes
  esenciales de la base (libc, util-linux, openssl, perl-base, ncurses). Solo
  bajan cambiando a una imagen base más chica.
- **Un caso lento en la librería.** Miles de facts con el mismo sujeto,
  nombrado en miles de oraciones: 4.000 de cada uno tardan 17 s. El servicio lo
  corta a los 10 s. Está en el README, en «Large inputs».
- **La precisión en la 0.2.x.** El redondeo a 28 dígitos del punto 2 sigue en
  la 0.2.2 publicada. Solo afecta a valores de más de 28 dígitos.
- **`/health` sin token.** Responde a cualquiera, con el estado y la versión.
- **Las acciones de GitHub** (`actions/*`) siguen por tag, y nada actualiza
  solo los commits de las acciones fijadas.
- **El digest del recibo** no tiene clave: prueba que el recibo es coherente,
  no quién lo escribió. Está en el README, en «Scope and limitations».
