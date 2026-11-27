"""Lectura de secretos. Un único sitio, un único formato.

`secrets.env` es `CLAVE=valor` literal tras el primer '='. Se eligió frente a
JSON porque una contraseña con comillas dobles rompe el JSON y aquí no
necesita escape (ocurrió en producción el 2026-11-09 con CDSE_PASSWORD).

Orden de precedencia: variable de entorno > secrets.env. Nunca se vuelca el
contenido del fichero en un log.
"""
import logging
import os

LOG = logging.getLogger("custody.creds")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV = os.path.join(HERE, "secrets.env")


def _parse(path):
    vals = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                vals[k.strip()] = v
    except OSError as exc:
        LOG.warning("%s ilegible (%s)", path, exc)
    return vals


def secret(name, default=None, path=None):
    """Valor de `name`. Entorno primero, luego secrets.env."""
    v = os.environ.get(name)
    if v:
        return v
    p = path or os.environ.get("CUSTODY_SECRETS") or DEFAULT_ENV
    if os.path.exists(p):
        return _parse(p).get(name) or default
    return default
