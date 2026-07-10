# Cloud Backend

Backend FastAPI unico per dashboard medico, app paziente, caregiver e integrazione MQTT.

## Scopo

Questa cartella contiene il backend Cloud del progetto. Al momento copre i blocchi D2 e
D3 della scaletta di Daniel:

```text
MQTT broker -> backend -> database -> dashboard/app
```

Stato attuale:

```text
D2 -> struttura FastAPI, health/ready, OpenAPI, errori e log
D3 -> PostgreSQL, SQLAlchemy models, Alembic migrations e test schema
D4 -> prossimo passo: subscriber MQTT e ingestione payload Edge
```

## Struttura

```text
cloud/backend/
  app/
    main.py
    api/
      router.py
      routes/
        auth.py
        patients.py
        telemetry.py
        alerts.py
        tasks.py
        notifications.py
        realtime.py
        health.py
    core/
      config.py
      errors.py
      logging.py
    db/
      base.py
      models.py
      session.py
    mqtt/
    schemas/
    services/
  alembic/
    env.py
    versions/
      20260710_0001_initial_schema.py
  scripts/
    export_openapi.py
  tests/
    test_database_schema.py
    test_health.py
  alembic.ini
  requirements.txt
```

## Avvio locale

Se serve anche il database reale locale, avviare prima PostgreSQL e applicare le
migrazioni:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
docker compose up -d postgres

cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m alembic upgrade head
```

Poi avviare il backend:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Endpoint:

```text
http://127.0.0.1:8080/health
http://127.0.0.1:8080/ready
http://127.0.0.1:8080/docs
http://127.0.0.1:8080/openapi.json
```

## Test

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m pytest
```

I test non richiedono broker MQTT o database reale. Lo schema DB viene verificato anche
con SQLite in memoria; PostgreSQL reale viene testato applicando Alembic sul servizio
Docker.

## Esportare OpenAPI

FastAPI espone sempre OpenAPI a runtime:

```text
http://127.0.0.1:8080/openapi.json
```

Per salvare il contratto condiviso usato da dashboard e app:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m scripts.export_openapi
```

Output:

```text
Documenti/contracts/openapi.json
```

## Configurazione

Le variabili usano prefisso:

```text
IOT_BACKEND_
```

Esempi:

```powershell
$env:IOT_BACKEND_ENVIRONMENT = "development"
$env:IOT_BACKEND_LOG_LEVEL = "INFO"
$env:IOT_BACKEND_MQTT_HOST = "localhost"
$env:IOT_BACKEND_MQTT_PORT = "8883"
$env:IOT_BACKEND_MQTT_USE_TLS = "true"
$env:IOT_BACKEND_DATABASE_URL = "postgresql+psycopg://iot_backend:IotBackendLocal001!@localhost:5432/progetto_iot"
```

## Database PostgreSQL

Avviare PostgreSQL locale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
docker compose up -d postgres
```

Applicare le migrazioni:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud\backend
.\.venv\Scripts\python -m alembic upgrade head
```

Controllare le tabelle:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
docker compose exec postgres psql -U iot_backend -d progetto_iot -c "\dt"
```

Backup locale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T postgres pg_dump -U iot_backend -d progetto_iot > backups\progetto_iot_backup.sql
```

Restore locale:

```powershell
cd C:\Users\Daniel\Desktop\ProgettoIoT\cloud
Get-Content backups\progetto_iot_backup.sql | docker compose exec -T postgres psql -U iot_backend -d progetto_iot
```

## Prossimi passi

- D4: collegare subscriber MQTT e ingestione.
- D5: implementare API reali per dashboard e app.
