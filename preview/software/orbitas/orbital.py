"""
orbital.py — nucleo de mecanica orbital, sin dependencias externas (solo stdlib).

Modelo:
  - Tierra esferica Re = 6378.137 km para geometria topocentrica (coherente con
    investigacion_preliminar/02_fisica_y_resolucion.md, que usa el mismo radio).
    Error de elevacion frente a WGS84 geodetico: <0.2 deg a 60 N. [SUPUESTO ACOTADO]
  - Propagacion: kepleriana con terminos seculares J2 (RAAN, argp, M).
    Sin arrastre, sin luni-solar, sin J3+. Valido para estadistica de cobertura
    en ventanas de dias-semanas. NO valido para mantenimiento de orbita ni para
    estabilidad a largo plazo de la HEO (eso exige propagador numerico).
  - Rotacion de la Tierra: GMST lineal, omega_e = 7.2921150e-5 rad/s.

Autor: CTO. Fecha: 2026-10-28.
"""

import math

# ---------------------------------------------------------------- constantes
MU = 398600.4418          # km^3/s^2  (WGS84/EGM96)
RE = 6378.137             # km        (WGS84 semieje ecuatorial)
J2 = 1.08262668e-3        # -
OMEGA_E = 7.2921150e-5    # rad/s
T_SID = 86164.0905        # s, dia sidereo
DEG = math.pi / 180.0
RAD = 180.0 / math.pi


# ---------------------------------------------------------------- utilidades
def kepler_E(M, e, tol=1e-12, itmax=60):
    """Resuelve M = E - e sin E. Newton con arranque robusto."""
    M = math.fmod(M, 2 * math.pi)
    if M < 0:
        M += 2 * math.pi
    E = M if e < 0.8 else math.pi
    for _ in range(itmax):
        f = E - e * math.sin(E) - M
        fp = 1.0 - e * math.cos(E)
        d = -f / fp
        E += d
        if abs(d) < tol:
            break
    return E


def nu_from_E(E, e):
    return 2.0 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2),
                            math.sqrt(1 - e) * math.cos(E / 2))


def period(a):
    return 2 * math.pi * math.sqrt(a ** 3 / MU)


def sma_from_period(T):
    return (MU * (T / (2 * math.pi)) ** 2) ** (1.0 / 3.0)


# ---------------------------------------------------------------- orbita
class Orbit:
    """Elementos keplerianos medios en epoca t=0, con deriva secular J2."""

    def __init__(self, name, a, e, inc_deg, raan_deg, argp_deg, M0_deg,
                 label=""):
        self.name = name
        self.label = label or name
        self.a = a
        self.e = e
        self.i = inc_deg * DEG
        self.raan0 = raan_deg * DEG
        self.argp0 = argp_deg * DEG
        self.M0 = M0_deg * DEG
        self.n = math.sqrt(MU / a ** 3)
        p = a * (1 - e ** 2)
        k = 1.5 * J2 * (RE / p) ** 2 * self.n
        self.draan = -k * math.cos(self.i)
        self.dargp = 0.5 * k * (5 * math.cos(self.i) ** 2 - 1)
        self.dM = self.n + 0.5 * k * math.sqrt(1 - e ** 2) * \
            (3 * math.cos(self.i) ** 2 - 1)
        self.T = period(a)
        self.rp = a * (1 - e)
        self.ra = a * (1 + e)

    def copy_with(self, **kw):
        d = dict(name=self.name, a=self.a, e=self.e,
                 inc_deg=self.i * RAD, raan_deg=self.raan0 * RAD,
                 argp_deg=self.argp0 * RAD, M0_deg=self.M0 * RAD,
                 label=self.label)
        d.update(kw)
        return Orbit(**d)

    def state_eci(self, t):
        """Posicion ECI [km] en el instante t [s] desde epoca."""
        raan = self.raan0 + self.draan * t
        argp = self.argp0 + self.dargp * t
        M = self.M0 + self.dM * t
        E = kepler_E(M, self.e)
        nu = nu_from_E(E, self.e)
        r = self.a * (1 - self.e * math.cos(E))
        u = argp + nu                      # argumento de latitud
        cu, su = math.cos(u), math.sin(u)
        co, so = math.cos(raan), math.sin(raan)
        ci, si = math.cos(self.i), math.sin(self.i)
        x = r * (cu * co - su * so * ci)
        y = r * (cu * so + su * co * ci)
        z = r * (su * si)
        return x, y, z, r

    def state_ecef(self, t, gmst0=0.0):
        x, y, z, r = self.state_eci(t)
        th = gmst0 + OMEGA_E * t
        ct, st = math.cos(th), math.sin(th)
        return (x * ct + y * st, -x * st + y * ct, z, r)

    def subpoint(self, t, gmst0=0.0):
        xe, ye, ze, r = self.state_ecef(t, gmst0)
        lat = math.asin(ze / r) * RAD
        lon = math.atan2(ye, xe) * RAD
        return lat, lon, r - RE


# ---------------------------------------------------------------- topocentrico
def site_vec(lat_deg, lon_deg):
    la, lo = lat_deg * DEG, lon_deg * DEG
    return (RE * math.cos(la) * math.cos(lo),
            RE * math.cos(la) * math.sin(lo),
            RE * math.sin(la))


def elev_range(sat_ecef, site):
    """Elevacion [deg] y distancia oblicua [km] desde un sitio ECEF."""
    sx, sy, sz = site
    rx, ry, rz = sat_ecef[0] - sx, sat_ecef[1] - sy, sat_ecef[2] - sz
    rho = math.sqrt(rx * rx + ry * ry + rz * rz)
    dot = (rx * sx + ry * sy + rz * sz) / (rho * RE)
    dot = max(-1.0, min(1.0, dot))
    return math.asin(dot) * RAD, rho


def foreshorten(el_deg):
    """Factor de escorzo en el eje de maxima deformacion = 1/sin(el)."""
    if el_deg <= 0:
        return float('inf')
    return 1.0 / math.sin(el_deg * DEG)


def airmass(el_deg):
    """Masa de aire plano-paralela 1/sin(el); valida hasta ~10 deg."""
    return foreshorten(el_deg)


# ---------------------------------------------------------------- L-shell
def lshell(x, y, z):
    """McIlwain L aproximada con dipolo centrado alineado: L = r/(Re cos^2 lam).

    Aproximacion deliberada: ignora el desplazamiento y la inclinacion del
    dipolo (y por tanto la Anomalia del Atlantico Sur). Sirve para contar
    travesias de cinturon y tiempo de residencia, NO para dosis. [SUPUESTO]
    """
    r = math.sqrt(x * x + y * y + z * z)
    lam = math.asin(z / r)
    c = math.cos(lam)
    if c < 1e-6:
        return 1e9
    return r / (RE * c * c)


# ---------------------------------------------------------------- constelacion
def phased_constellation(orb, n):
    """n satelites sobre la MISMA traza terrestre, separados T/n en el tiempo.

    Sat k va adelantado dM = 2 pi k/n; para que su traza coincida hay que
    retrasar el nodo: RAAN_k = RAAN_0 - omega_e * (k T / n).
    """
    out = []
    for k in range(n):
        dt = k * orb.T / n
        out.append(orb.copy_with(
            M0_deg=(orb.M0 * RAD + 360.0 * k / n) % 360.0,
            raan_deg=(orb.raan0 * RAD - OMEGA_E * dt * RAD) % 360.0))
    return out


def walker_delta(orb, planes, per_plane, F=1):
    """Walker delta i:T/P/F sobre orbita circular (para LEO/MEO)."""
    out = []
    T_tot = planes * per_plane
    for p in range(planes):
        for s in range(per_plane):
            raan = orb.raan0 * RAD + 360.0 * p / planes
            M = orb.M0 * RAD + 360.0 * s / per_plane + 360.0 * F * p / T_tot
            out.append(orb.copy_with(raan_deg=raan % 360.0,
                                     M0_deg=M % 360.0))
    return out


# ---------------------------------------------------------------- formato
def md_table(headers, rows, aligns=None):
    cols = len(headers)
    aligns = aligns or ['---'] * cols
    out = ['| ' + ' | '.join(str(h) for h in headers) + ' |',
           '|' + '|'.join(aligns) + '|']
    for r in rows:
        out.append('| ' + ' | '.join(str(c) for c in r) + ' |')
    return '\n'.join(out)
