# Revisión de observaciones de M8ven

Fecha: 2026-11-19. Basada en el informe privado compartido por el publicador,
que identifica el commit `1e8abbd`, y en el código actual del repositorio.
Los cambios locales y las pruebas no actualizan por sí mismos el índice de
M8ven. La verificación del publicador y un nuevo análisis siguen dependiendo
del servicio externo.

| Observación | Evidencia y resolución |
|---|---|
| No se encontró política de privacidad | Se agrega `PRIVACY.md`, enlazada desde el README y desde `[project.urls]` en `pyproject.toml`. Describe cada modo, destinos, credenciales, recibos, almacenamiento y contacto. Pendiente de que M8ven la detecte en un nuevo análisis. |
| Sin homepage para cotejar dominio | `pyproject.toml` ya declara `Homepage` con el repositorio oficial. No hay dominio de servicio propio ni scope npm que corresponda agregar. Pedir que M8ven distinga ausencia de un dominio independiente de ausencia de homepage. |
| No se pudieron resolver handlers | `build_server()` en `antihallucination/mcp_server.py` registra cuatro funciones con `@built.tool`, que llaman a `run_prepare`, `run_compose`, `run_verify` y `run_check_receipt`. El mismo informe aprueba las cuatro descripciones: solicitar aclaración del resultado contradictorio. |
| Tres hosts detectados | Son presets de `OpenAICompatibleWriter`, no llamadas salientes de las cuatro herramientas MCP. También existe el writer opcional de Anthropic y se permiten endpoints personalizados. La política y el README aclaran el alcance. |
| Cuarto host en el análisis del 2026-11-20 (`6665d13`) | `(127\.0\.0\.1\|localhost\|\[::1\])(:\d+)?` no es un host: es la regex que valida el header `Origin` en `antihallucination/http_server.py`, agregada en `f12ca36`, después del análisis anterior. El escáner la leyó como dirección porque seguía a `http://`. `_LOCAL_ORIGIN` ahora se arma con el patrón de `_LOCAL_HOST_HEADER`, sin cambiar lo que acepta; queda ver si el próximo análisis deja de listarla. |
| Sin lectura del servidor en ejecución | `tests/test_mcp_server.py` verifica las cuatro herramientas con el cliente del SDK, también lanzando un proceso por stdio. `tests/test_http_server.py` cubre MCP sobre HTTP. Estas pruebas locales no equivalen a una ejecución por M8ven; pedir reanálisis externo. |

## Precisiones sobre los controles aprobados

- **Autenticación:** el servicio HTTP implementa un token Bearer compartido
  (`TokenGate`), no un servidor OAuth. El MCP por stdio no usa un login de red.
- **Límites:** hay topes por tamaño, tiempo, memoria y concurrencia; no hay
  un limitador de peticiones por minuto o por identidad. Un proxy puede
  aplicar esa política según el despliegue. El resultado «Rate limiting
  detected» no demuestra que exista ese control en la aplicación.
- **Recibos:** guardan datos y textos para reproducir decisiones; los hashes
  de fuentes no convierten el recibo completo en anónimo ni cifrado.

## Verificación local

Comando para comprobar el MCP, el servicio HTTP y los ejemplos del README:

```bash
python -m pytest tests/test_mcp_server.py tests/test_http_server.py tests/test_readme.py -q
```

Resultado local del 2026-11-19, Python 3.14 en Windows: **67 pruebas
aprobadas y 1 omitida**. La omitida requiere el módulo `resource` para
comprobar el límite de memoria, que no está disponible en Windows. Se
comprobaron también el parseo TOML y los enlaces a la política de privacidad.

No se cambian los handlers para satisfacer un resultado contradictorio del
escáner. Las cuatro herramientas ya declaran sus cuatro anotaciones y tienen
cobertura de protocolo; cualquier cambio de comportamiento requeriría un
problema reproducible.
