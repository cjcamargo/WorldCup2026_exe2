# Polla Mundialista Exe2

Aplicacion Streamlit para administrar pollas del Mundial 2026 con usuarios, grupos privados, predicciones, auditoria, resultados automaticos y rankings independientes.

La interfaz principal ya no depende de archivos Excel. Las predicciones nuevas se guardan directamente en Supabase y la automatizacion de GitHub Actions actualiza resultados, posiciones y puntajes.

## Funcionalidades

- Acceso mediante usuario y PIN.
- Creacion de grupos con codigo de invitacion.
- Solicitudes para unirse a un grupo con aprobacion del administrador.
- Maximo de 10 miembros activos por grupo.
- Usuarios globalmente unicos.
- Cambio de PIN desde `Mi cuenta`.
- Predicciones de marcadores con indicador persistente `Guardado`.
- Cierre diario de predicciones: primer kickoff del dia + 1 minuto o 2:00 p. m., lo que ocurra primero.
- Predicciones de todos los integrantes visibles solo cuando el partido ya esta bloqueado.
- Top 3 por grupo y campeon, subcampeon y tercer puesto.
- Ranking independiente para cada grupo de polla.
- Grupo `Exe2 Knockout` independiente, con los 32 partidos eliminatorios y ranking iniciado en cero.
- Pronostico eliminatorio al finalizar 90 minutos, mas equipo clasificado.
- Actualizacion automatica del bracket con ganadores y perdedores confirmados.
- Resultados confirmados automaticamente.
- Tabla de posiciones de los grupos obtenida desde ESPN.
- Fallback calculado desde resultados confirmados si ESPN no esta disponible.
- Filtros por grupo y calendario.
- Informacion de televisacion por partido.
- Auditoria de cambios y correos agrupados.
- Interfaz responsive en modo claro y oscuro.

## Navegacion

La aplicacion muestra estas secciones:

1. `Mis marcadores`: registro y edicion de predicciones antes del cierre.
2. `Predicciones`: pronosticos del grupo revelados despues del bloqueo de cada partido.
3. `Posiciones`: tabla ESPN y resultados confirmados filtrables.
4. `Ranking`: clasificacion de participantes del grupo activo.
5. `Top 3 grupos`: posiciones finales pronosticadas para cada grupo.
6. `Finales`: campeon, subcampeon y tercer puesto.
7. `Detalle`: desglose de puntos por participante y partido.
8. `Mi cuenta`: PIN, grupos, codigos y membresias.
9. `Admin`: solicitudes pendientes y controles administrativos.

## Reglas de puntuacion

Los puntos por partido son acumulativos:

| Criterio | Puntos |
| --- | ---: |
| Marcador exacto | 2 |
| Ganador o empate correcto | 3 |
| Goles correctos de cada equipo | 1 por equipo |
| Diferencia de gol correcta | 1 |

Un marcador exacto suma un maximo de **8 puntos**.

En `Exe2 Knockout`, los goles se puntuan con el marcador al finalizar 90 minutos. Los 3 puntos de ganador se asignan al equipo que clasifica; si el marcador pronosticado termina empatado, el usuario debe elegir quien avanza.

Picks adicionales:

| Criterio | Puntos |
| --- | ---: |
| Primero del grupo en posicion exacta | 5 |
| Segundo del grupo en posicion exacta | 3 |
| Tercero del grupo en posicion exacta | 2 |
| Campeon | 18 |
| Subcampeon | 9 |
| Tercer puesto | 5 |

La configuracion editable esta en `config/puntajes.json`.

## Arquitectura

```text
Streamlit Cloud
    |
    +-- app.py
    |
    +-- Supabase
          users
          polla_groups
          group_memberships
          matches
          predictions
          group_picks
          final_picks
          results
          audit_log
          settings
          ranking
          detail

GitHub Actions
    |
    +-- scripts/update_app_backend.py
          consulta resultados
          consulta posiciones ESPN
          recalcula rankings
          envia alertas agrupadas
```

## Requisitos

- Python 3.12 recomendado.
- Cuenta de Supabase.
- Repositorio de GitHub.
- Streamlit Community Cloud.
- Gmail con verificacion en dos pasos y App Password para alertas.

Instala las dependencias:

```powershell
pip install -r requirements.txt
```

## Configurar Supabase

1. Crea un proyecto en Supabase.
2. Abre `SQL Editor`.
3. Ejecuta completo `supabase/schema.sql`.
4. Copia desde la configuracion del proyecto:
   - Project URL.
   - Service role key.

La service role key es secreta. No debe guardarse en Git ni exponerse en el navegador.

### Actualizar una instalacion existente para knockout

No reemplaces ni borres las tablas actuales. Ejecuta una sola vez en `Supabase > SQL Editor` el contenido de:

```text
supabase/migrations/20260628_knockout_group.sql
```

La migracion conserva las predicciones de `Exe2`, las asocia al grupo original, crea `Exe2 Knockout` (`EXE2KO`), agrega como miembros activos a `CarlosF`, `Alex`, `Oscar`, `Charlie` y `Eduard`, e incorpora `M073-M104`.

### Inicializar datos

Puedes ejecutar:

```powershell
$env:SUPABASE_URL="https://TU-PROYECTO.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY="TU_SERVICE_ROLE_KEY"
python scripts/init_supabase.py --default-pin "1234" --admin-pin "admin123"
```

Tambien puedes ejecutar manualmente:

```text
GitHub > Actions > Init Supabase Backend > Run workflow
```

El script carga usuarios iniciales, calendario, resultados existentes y el grupo base `Exe2`.

## Ejecutar localmente

Crea `.streamlit/secrets.toml`:

```toml
POLLA_SMTP_USER = "remitente@gmail.com"
POLLA_SMTP_PASSWORD = "abcd efgh ijkl mnop"

[supabase]
url = "https://TU-PROYECTO.supabase.co"
service_role_key = "TU_SERVICE_ROLE_KEY"
```

Los secretos SMTP deben estar antes de `[supabase]` para que sean claves de nivel superior.

La contrasena SMTP es una **App Password de Google**, no la contrasena normal de Gmail.

Ejecuta:

```powershell
streamlit run app.py
```

## Despliegue en Streamlit Cloud

1. Conecta el repositorio de GitHub.
2. Selecciona `app.py` como archivo principal.
3. Agrega en `App settings > Secrets` el mismo contenido de `secrets.toml`.
4. Comparte el proyecto Supabase con la configuracion correspondiente.
5. Reinicia la app despues de cambiar secretos.

Aplicacion desplegada:

```text
https://worldcup2026exe2.streamlit.app
```

## Automatizacion

El workflow principal es:

```text
.github/workflows/update-polla.yml
```

Se puede iniciar de tres formas:

- Cron de GitHub Actions a los minutos 7 y 42 de cada hora.
- Ejecucion manual con `workflow_dispatch`.
- Cron externo mediante `repository_dispatch` con tipo `update-polla-backend`.

Ejecuta:

```text
python scripts/update_app_backend.py
```

En cada corrida:

1. Consulta partidos cuyo resultado ya deberia estar disponible.
2. Usa ESPN como primera fuente y fuentes de respaldo configuradas.
3. En eliminatorias separa marcador a 90 minutos, marcador a 120 minutos, penales y equipo clasificado.
4. Actualiza automaticamente los equipos del siguiente cruce del bracket.
5. Guarda resultados confirmados en Supabase.
6. Consulta las tablas de posiciones de ESPN.
7. Si ESPN falla, calcula posiciones desde los resultados confirmados.
8. Recalcula ranking y detalle para cada grupo de polla.
9. Envia un unico correo agrupado con cambios nuevos.
10. Registra la fecha de la ultima ejecucion.

Secrets requeridos en GitHub:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
POLLA_SMTP_USER
POLLA_SMTP_PASSWORD
```

Ejecucion manual:

```text
GitHub > Actions > Update Polla Backend > Run workflow
```

El workflow `schedule-canary.yml` permite comprobar si GitHub esta disparando tareas programadas. Los cron de GitHub pueden retrasarse o saltarse; para mayor confiabilidad se recomienda mantener un cron externo que invoque `repository_dispatch`.

### Recordatorio diario de predicciones

El workflow:

```text
.github/workflows/daily-prediction-reminder.yml
```

es ejecutado por un cron externo todos los dias a las **8:05 a. m. hora Bogota** (`13:05 UTC`). Envia un correo individual a los destinatarios configurados en `config/recordatorios.json` con:

- Partidos del dia.
- Partidos de fase de grupos y eliminatorias.
- Horarios en Bogota.
- Grupo y canales de television.
- Recordatorio del cierre diario: primer kickoff + 1 minuto o 2:00 p. m., lo que ocurra primero.
- Enlace directo a la app.

El workflow no usa `schedule` de GitHub, para evitar retrasos, omisiones o envios duplicados. El cron externo debe invocar:

```text
POST https://api.github.com/repos/cjcamargo/WorldCup2026_exe2/dispatches
```

Headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer TU_GITHUB_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

Body:

```json
{
  "event_type": "daily-prediction-reminder"
}
```

Configura el cron externo en zona horaria `America/Bogota` a las `08:05`, o en UTC con expresion:

```text
5 13 * * *
```

Usa un fine-grained personal access token limitado solamente al repositorio `WorldCup2026_exe2`. El token debe guardarse como secreto en el proveedor del cron y nunca en el repositorio.

Tambien puede ejecutarse manualmente:

```text
GitHub > Actions > Daily Prediction Reminder > Run workflow
```

Para probarlo localmente sin enviar:

```powershell
python scripts/send_daily_reminder.py --dry-run
python scripts/send_daily_reminder.py --dry-run --date 2026-06-19
```

## Fuentes de datos

### Resultados

Configurados en `config/resultados.json`:

- ESPN World Cup scoreboard como fuente principal.
- Wikipedia como respaldo.
- SB Nation como respaldo adicional.
- Coincidencia flexible de nombres mediante RapidFuzz.

### Tabla de posiciones

El update consulta standings de ESPN y conserva el orden publicado por la fuente, incluyendo sus criterios de desempate.

Cuando se selecciona una fecha historica, la app calcula una tabla provisional hasta esa fecha usando los resultados confirmados. Esa tabla historica no incluye criterios externos como fair play.

### Televisacion

Los canales se guardan en:

```text
config/televisacion.json
```

El archivo fue validado contra el calendario de canales y se relaciona con los partidos por equipos, no por numero de fila.

Para reconstruirlo desde un Excel compatible:

```powershell
python scripts/build_televisacion_from_excel.py "ruta\calendario_mundial_2026_canales.xlsx"
```

## Alertas por correo

La configuracion esta en `config/alertas.json`.

Se utilizan para:

- Cambios detectados en predicciones.
- Solicitudes para unirse a grupos.

Las alertas de auditoria se agrupan en un solo correo por corrida.

## Archivos principales

```text
app.py                              Aplicacion Streamlit
polla/supabase_store.py             Acceso a Supabase
polla/prediction_rules.py           Cierre diario y visibilidad
polla/results.py                    Consulta y conciliacion de resultados
polla/standings.py                  Posiciones ESPN y fallback
polla/scoring.py                    Sistema de puntos
scripts/update_app_backend.py        Job automatico
scripts/init_supabase.py             Inicializacion del backend
supabase/schema.sql                  Esquema de base de datos
supabase/migrations/                 Migraciones incrementales
config/calendario_partidos.json      Calendario en hora Bogota
config/calendario_eliminatorias.json Bracket knockout en hora Bogota
config/resultados.json               Fuentes y ventanas de consulta
config/televisacion.json             Canales por partido
config/puntajes.json                 Reglas de puntuacion
config/recordatorios.json            Destinatarios del correo diario
scripts/send_daily_reminder.py        Recordatorio de partidos
```

## Pruebas

```powershell
python -m pytest tests
python -m compileall app.py polla scripts tests
```

## Flujo legado de Excel y Google Drive

El repositorio conserva el flujo original basado en Excel:

```text
scripts/run_polla.py
scripts/auth_google_drive.py
polla/excel_reader.py
polla/drive.py
```

Este flujo sirve como respaldo o migracion, pero **no es la interfaz principal actual**. Las predicciones nuevas deben hacerse desde Streamlit y guardarse en Supabase.

Comandos disponibles:

```powershell
python scripts/run_polla.py --dry-run
python scripts/run_polla.py --audit-only --dry-run
python scripts/run_polla.py --results-only --dry-run
python scripts/run_polla.py --rebuild-ranking --dry-run
```

## Seguridad

- Nunca subir `.streamlit/secrets.toml`.
- Nunca subir la service role key.
- Nunca guardar una App Password de Gmail en archivos versionados.
- Mantener Supabase y GitHub Secrets separados de configuraciones publicas.
- Los PIN se almacenan hasheados y ligados al nombre del participante.
