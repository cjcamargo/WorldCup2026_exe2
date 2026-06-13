# Polla Mundialista

Automatizacion para leer los Excel de participantes, auditar cambios, consultar resultados y generar ranking.

## Ejecucion

Usa el Python empaquetado por Codex:

```powershell
& "C:\Users\RentAdvisor\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\run_polla.py --dry-run
```

Modos utiles:

```powershell
& "C:\Users\RentAdvisor\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\run_polla.py --audit-only --dry-run
& "C:\Users\RentAdvisor\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\run_polla.py --results-only --dry-run
& "C:\Users\RentAdvisor\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\run_polla.py --rebuild-ranking --dry-run
```

## Configuracion

- `config/participantes.json`: archivos de Drive por participante.
- `config/google_drive.json`: sincronizacion automatica con Google Drive API.
- `config/puntajes.json`: reglas acumulativas de puntos.
- `config/alertas.json`: correo destino y SMTP.
- `config/extractor.json`: mapeo de la plantilla Excel.
- `config/calendario_partidos.json`: calendario base en hora Bogota.
- `config/resultados.json`: fuentes y ventanas de consulta de resultados.

## Correo

El correo de alertas esta configurado para enviar un solo resumen agrupado por corrida a:

```text
carlosjeyson10@gmail.com
```

Para que Gmail permita el envio real, define estas variables de entorno:

```powershell
$env:POLLA_SMTP_USER="carlosjeyson10@gmail.com"
$env:POLLA_SMTP_PASSWORD="app_password"
```

Para que queden persistentes en Windows:

```powershell
setx POLLA_SMTP_USER "carlosjeyson10@gmail.com"
setx POLLA_SMTP_PASSWORD "app_password"
```

Usa una App Password de Gmail, no la clave normal de la cuenta.

## Nota importante

El extractor empieza en modo heuristico. Para produccion conviene ajustar `config/extractor.json` con las celdas exactas de la plantilla, porque eso reduce falsos positivos.

## Sincronizacion automatica con Google Drive

El flujo esta preparado para no depender de descargas manuales. Requiere una autorizacion OAuth una sola vez.

1. En Google Cloud, crea un OAuth Client de tipo `Desktop app`.
2. Descarga el JSON del cliente OAuth.
3. Guardalo como:

```text
data/secrets/google_oauth_client.json
```

4. Ejecuta la autorizacion inicial:

```powershell
& "C:\Users\RentAdvisor\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\auth_google_drive.py
```

5. Se abrira el navegador. Acepta el permiso de solo lectura de Drive.
6. Desde ese momento, `scripts\run_polla.py` descarga automaticamente los Excel con el token guardado en `data/secrets/google_drive_token.json`.

Los archivos dentro de `data/secrets/` no se versionan.

## Ranking online

El ranking tambien se publica como Google Sheet:

```text
https://docs.google.com/spreadsheets/d/1HzimDaKvvga0Wc3gxoC-HIDRhYwsSuN4hORDumc8SQc/edit
```

La automatizacion usa `config/publicacion.json` para saber que archivo debe actualizar.

Para que los participantes puedan verlo, configurar una sola vez en Google Drive:

1. Abrir el Google Sheet.
2. Clic en `Compartir`.
3. En `Acceso general`, seleccionar `Cualquier persona con el enlace`.
4. Dejar rol `Lector`.
5. Copiar ese enlace y enviarlo por WhatsApp.

## App Streamlit

La app principal esta en:

```text
app.py
```

### Inicializar Supabase

1. Crea un proyecto en Supabase.
2. Ve a `SQL Editor`.
3. Copia y ejecuta el contenido de `supabase/schema.sql`.
4. En `Project Settings > API`, copia `Project URL` y `service_role key`.
5. Inicializa datos base:

```powershell
python scripts\init_supabase.py --url "SUPABASE_URL" --service-role-key "SUPABASE_SERVICE_ROLE_KEY" --default-pin "1234" --admin-pin "admin123"
```

Esto carga estas tablas:

```text
users, matches, predictions, group_picks, final_picks, results, audit_log, settings, ranking, detail
```

### Ejecutar local

Instala dependencias:

```powershell
pip install -r requirements.txt
```

Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` y completa:

```toml
[supabase]
url = "SUPABASE_URL"
service_role_key = "SUPABASE_SERVICE_ROLE_KEY"
```

Luego ejecuta:

```powershell
streamlit run app.py
```

### Deploy en Streamlit Cloud

1. Sube el repo a GitHub.
2. Crea una app en Streamlit Cloud apuntando a `app.py`.
3. En `Secrets`, pega el contenido equivalente a `.streamlit/secrets.toml`.
4. Confirma que Supabase tenga las tablas creadas con `supabase/schema.sql`.

## Automatizacion con GitHub Actions

El workflow `.github/workflows/update-polla.yml` ejecuta cada hora:

```text
python scripts/update_app_backend.py
```

Hace:

- consulta resultados pendientes,
- actualiza `Results`,
- recalcula `Ranking` y `Detail`,
- envia un solo correo agrupado con cambios nuevos de `AuditLog`.

Configura estos secrets en GitHub:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
POLLA_SMTP_USER
POLLA_SMTP_PASSWORD
```

`SUPABASE_SERVICE_ROLE_KEY` es sensible. Guardalo solo en GitHub Secrets y Streamlit Secrets; no lo subas al repo.

Tambien puedes ejecutarlo manualmente desde GitHub en `Actions > Update Polla Backend > Run workflow`.
