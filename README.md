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

### Inicializar Google Sheet backend

1. Crea una Service Account en Google Cloud.
2. Comparte el Google Sheet backend con el correo de la Service Account como `Editor`.
3. Ejecuta:

```powershell
python scripts\init_app_sheets.py --spreadsheet-id "ID_DEL_GOOGLE_SHEET_BACKEND" --service-account-json "ruta\service-account.json" --default-pin "1234" --admin-pin "admin123"
```

Esto crea/actualiza estas pestañas:

```text
Users, Matches, Predictions, GroupPicks, FinalPicks, Results, AuditLog, Settings, Ranking, Detail
```

### Ejecutar local

Instala dependencias:

```powershell
pip install -r requirements.txt
```

Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` y completa:

```toml
[google_sheets]
spreadsheet_id = "ID_DEL_GOOGLE_SHEET_BACKEND"

[gcp_service_account]
# contenido del JSON de la service account
```

Luego ejecuta:

```powershell
streamlit run app.py
```

### Deploy en Streamlit Cloud

1. Sube el repo a GitHub.
2. Crea una app en Streamlit Cloud apuntando a `app.py`.
3. En `Secrets`, pega el contenido equivalente a `.streamlit/secrets.toml`.
4. Confirma que la Service Account tenga permiso de editor sobre el Google Sheet backend.
