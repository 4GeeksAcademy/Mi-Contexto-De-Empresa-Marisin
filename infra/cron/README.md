# `infra/cron` — disparador del script nocturno

El script `scripts/nightly_export.py` (Ticket #DEV-53) lo dispara el **crontab
del sistema operativo**, fuera del proceso de FastAPI.

| Campo | Valor |
|---|---|
| Expresión cron | `15 1 * * *` (todos los días, 01:15 UTC) |
| Comando | `cd <repo> && mkdir -p logs && .venv/bin/python scripts/nightly_export.py >> logs/nightly_export.log 2>&1` |
| Log | `logs/nightly_export.log` (no se versiona) |
| Fichero | [`nightly_export.crontab`](./nightly_export.crontab) |

## Por qué crontab y no el scheduler del framework

- **Independencia de la API:** el ticket prohíbe ejecutar el job dentro de
  FastAPI (`APScheduler`, `@repeat_every`, lifespan). Con cron es otro proceso,
  con otro PID: no comparte hilo, event loop ni workers con uvicorn, y un
  reinicio de la API no lo interrumpe.
- **Sin proceso extra encendido:** el `--serve` de Prefect del pipeline necesita
  un proceso de larga vida escuchando; cron ya viene con el sistema y no consume
  nada entre ejecuciones.
- **El lock y la idempotencia no dependen del disparador:** viven en `job_runs`.
  Si cron dispara dos veces, o alguien lo lanza a mano a la vez, la segunda
  instancia aborta igual.
- **Producción:** lo recomendable es el mismo crontab dentro de un **contenedor
  scheduler dedicado** (o un cron gestionado) que esté siempre encendido. En el
  Codespace no se crea esa imagen porque el disco va justo (Docker ocupa gran
  parte) y el Codespace se suspende cuando está inactivo: allí cron solo corre
  mientras el Codespace está encendido.

## Instalación en el Codespace

```bash
date -u                                   # comprobar que el sistema está en UTC
sudo apt-get update && sudo apt-get install -y cron   # paquete del SO, no del proyecto
sudo service cron start
sed "s#__REPO_ROOT__#$(pwd)#g" infra/cron/nightly_export.crontab | crontab -
crontab -l
```

Tras reiniciar o reconstruir el Codespace hay que volver a ejecutar
`sudo service cron start` (y la instalación si se reconstruyó).

## Prueba rápida del disparador

Instala temporalmente una línea que corre cada minuto sobre un día fijo; la
primera ejecución completa el día y las siguientes registran la omisión por
duplicado (idempotencia):

```bash
mkdir -p logs
echo "* * * * * cd $(pwd) && TARGET_DATE=2026-11-18 .venv/bin/python scripts/nightly_export.py >> logs/nightly_export.log 2>&1" | crontab -
sleep 150 && tail -n 20 logs/nightly_export.log
sed "s#__REPO_ROOT__#$(pwd)#g" infra/cron/nightly_export.crontab | crontab -   # restaurar
crontab -l
```
