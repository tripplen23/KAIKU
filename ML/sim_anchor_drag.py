#!/usr/bin/env python3
"""3-DOF Fossen Multi-Hull + Quasi-Static Catenary + DNV-RP-E301 Stick-Slip Simulator & Tier-2 Trainer.

Simulates 3 realistic Baltic vessel hull profiles (inspired by Fossen MSS) transiting the
Gulf of Finland subsea cable corridor (59.85°N, 25.50°E) over 45-minute episodes sampled at
dt = 60-90 s with realistic Class-A AIS sensor noise:
  1. aframax_tanker (Lpp = 228 m, B = 42 m, anchor 12-16 t, shipType 80)
  2. mariner_cargo  (Lpp = 160 m, B = 24 m, anchor 6-9 t, shipType 70)
  3. coastal_feeder (Lpp = 85 m,  B = 14 m, anchor 2.5-4 t, shipType 70)

Generates 1,500 labeled episodes across 3 operational regimes (500 each):
  - normal: steady cruising under 5-28 kn wind, 0-0.6 kn current, 20-140 m depth.
  - benign_slowdown: smooth or two-notch engine throttle reduction across 20-140 m depth
    (including deep water > 115 m where a lowered anchor hangs above seabed as negatives).
  - anchor_drag: port/starboard hawsepipe drop (y_h = +/-0.08 B) while under engine power
    over reachable seabed (20-105 m) with quasi-static catenary tension and DNV-RP-E301
    stick-slip resistance (soil factor 3.5-8.5).

Trains a calibrated L2-regularized Logistic Regression (Tier-2) on 5 AIS+depth observable
features over a 70% / 30% split stratified by (regime, hull_class), exports the dataset CSV,
weights JSON (to ML/weights/ and custody_mvp/custody/weights/), and validation plot PNG.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
import os
import shutil
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
CUSTODY_MVP_DIR: str = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "preview", "software", "custody_mvp")
)
DEFAULT_WEIGHTS_PATH: str = os.path.join(SCRIPT_DIR, "weights", "ship_motion_mlp.json")
DEFAULT_PLOT_PATH: str = os.path.join(
    SCRIPT_DIR, "data", "eval_data", "sim_anchor_drag_validation.png"
)
DEFAULT_DATASET_PATH: str = os.path.join(
    SCRIPT_DIR, "data", "train_data", "sim_anchor_drag_dataset.csv"
)
DEFAULT_TIER2_WEIGHTS_PATH: str = os.path.join(
    SCRIPT_DIR, "weights", "anchor_drag_tier2.json"
)
DEFAULT_CUSTODY_TIER2_PATH: str = os.path.join(
    CUSTODY_MVP_DIR, "custody", "weights", "anchor_drag_tier2.json"
)

TIER2_FEATURE_NAMES: List[str] = [
    "peak_radial_z_capped",
    "braking_kn",
    "unilateral_crab_deg",
    "crab_sign_consistency",
    "seabed_reachable",
]
TIER2_THRESHOLDS: Dict[str, float] = {"high": 0.70, "moderate": 0.35}
TIER2_PROVENANCE: str = "physics-sim-tier2 (3-DOF Fossen + Catenary, 3 hull classes)"

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
if CUSTODY_MVP_DIR not in sys.path:
    sys.path.insert(0, CUSTODY_MVP_DIR)

os.environ.setdefault("KAIKU_MLP_WEIGHTS", DEFAULT_WEIGHTS_PATH)

import mlp_infer
from custody import geo as custody_geo
from custody import indicators as custody_ind
from custody import motion as custody_motion

KNOTS_TO_MS: float = 0.5144444444444445
MS_TO_KNOTS: float = 1.9438444924406046
SHACKLE_M: float = 27.5
GRAVITY_MS2: float = 9.80665
RHO_WATER_KGM3: float = 1025.0
RHO_AIR_KGM3: float = 1.225
BASE_EPOCH_MS: int = 1735120800000  # 2024-12-25T10:00:00Z in ms


@dataclass(frozen=True)
class VesselHullParams:
    """Hydrodynamic and geometric parameters for a 3-DOF Fossen Baltic vessel profile."""

    hull_name: str = "aframax_tanker"
    ship_type: int = 80
    lpp_m: float = 228.0
    beam_m: float = 42.0
    draft_m: float = 13.5
    mass_kg: float = 8.50e7
    m_u_kg: float = 8.925e7
    m_v_kg: float = 1.530e8
    i_r_kgm2: float = 4.700e11
    c_xu_kgm: float = 28500.0
    c_xvv_kgm: float = 95000.0
    c_yv_kgm: float = 3.80e5
    c_yvv_kgm: float = 1.25e6
    c_yr_kg: float = 4.20e7
    c_nr_kgm: float = 3.60e10
    c_nrr_kgm2: float = 6.50e10
    c_nv_kg: float = 1.80e7
    c_ydelta_kgm: float = 1.35e5
    kp_rudder: float = 2.8
    kd_rudder: float = 38.0
    ki_rudder: float = 0.035
    max_rudder_rad: float = math.radians(35.0)
    area_frontal_m2: float = 920.0
    area_lateral_m2: float = 3100.0
    cx_wind: float = 0.65
    cy_wind: float = 0.82
    cn_wind: float = 0.14
    submerged_chain_w_nm: float = 2250.0
    anchor_weight_min_t: float = 12.0
    anchor_weight_max_t: float = 16.0
    cruise_min_kn: float = 10.0
    cruise_max_kn: float = 13.5


TankerParams = VesselHullParams


HULL_PROFILES: Dict[str, VesselHullParams] = {
    "aframax_tanker": VesselHullParams(
        hull_name="aframax_tanker",
        ship_type=80,
        lpp_m=228.0,
        beam_m=42.0,
        draft_m=13.5,
        mass_kg=8.50e7,
        m_u_kg=8.925e7,
        m_v_kg=1.530e8,
        i_r_kgm2=4.700e11,
        c_xu_kgm=28500.0,
        c_xvv_kgm=95000.0,
        c_yv_kgm=3.80e5,
        c_yvv_kgm=1.25e6,
        c_yr_kg=4.20e7,
        c_nr_kgm=3.60e10,
        c_nrr_kgm2=6.50e10,
        c_nv_kg=1.80e7,
        c_ydelta_kgm=1.35e5,
        kp_rudder=2.8,
        kd_rudder=38.0,
        ki_rudder=0.035,
        area_frontal_m2=920.0,
        area_lateral_m2=3100.0,
        submerged_chain_w_nm=2250.0,
        anchor_weight_min_t=12.0,
        anchor_weight_max_t=16.0,
        cruise_min_kn=10.0,
        cruise_max_kn=13.5,
    ),
    "mariner_cargo": VesselHullParams(
        hull_name="mariner_cargo",
        ship_type=70,
        lpp_m=160.0,
        beam_m=24.0,
        draft_m=9.0,
        mass_kg=2.27e7,
        m_u_kg=2.38e7,
        m_v_kg=4.09e7,
        i_r_kgm2=6.18e10,
        c_xu_kgm=10900.0,
        c_xvv_kgm=36000.0,
        c_yv_kgm=1.78e5,
        c_yvv_kgm=5.85e5,
        c_yr_kg=1.38e7,
        c_nr_kgm=5.82e9,
        c_nrr_kgm2=1.05e10,
        c_nv_kg=5.90e6,
        c_ydelta_kgm=3.60e4,
        kp_rudder=2.8,
        kd_rudder=26.0,
        ki_rudder=0.035,
        area_frontal_m2=410.0,
        area_lateral_m2=1520.0,
        submerged_chain_w_nm=1350.0,
        anchor_weight_min_t=6.0,
        anchor_weight_max_t=9.0,
        cruise_min_kn=11.0,
        cruise_max_kn=15.5,
    ),
    "coastal_feeder": VesselHullParams(
        hull_name="coastal_feeder",
        ship_type=70,
        lpp_m=85.0,
        beam_m=14.0,
        draft_m=5.2,
        mass_kg=4.07e6,
        m_u_kg=4.27e6,
        m_v_kg=7.33e6,
        i_r_kgm2=3.13e9,
        c_xu_kgm=3660.0,
        c_xvv_kgm=12200.0,
        c_yv_kgm=5.45e4,
        c_yvv_kgm=1.80e5,
        c_yr_kg=2.25e6,
        c_nr_kgm=2.68e8,
        c_nrr_kgm2=4.84e8,
        c_nv_kg=9.60e5,
        c_ydelta_kgm=7.80e3,
        kp_rudder=2.8,
        kd_rudder=16.0,
        ki_rudder=0.035,
        area_frontal_m2=150.0,
        area_lateral_m2=520.0,
        submerged_chain_w_nm=750.0,
        anchor_weight_min_t=2.5,
        anchor_weight_max_t=4.0,
        cruise_min_kn=9.2,
        cruise_max_kn=13.0,
    ),
}


@dataclass(frozen=True)
class EpisodeConfig:
    """Configuration parameters for a single 45-minute 3-DOF vessel simulation episode."""

    mmsi: int
    regime: str
    lat0_deg: float
    lon0_deg: float
    heading_ref_deg: float
    u_cruise_kn: float
    u_target_slow_kn: float
    t_maneuver_s: float
    slowdown_ramp_s: float
    wind_speed_kn: float
    wind_from_deg: float
    current_speed_kn: float
    current_to_deg: float
    depth_m: float
    chain_shackles: float
    anchor_weight_t: float
    eta_soil: float
    hawsepipe_side: int
    hull_class: str = "aframax_tanker"
    ship_type: int = 80
    yaw_osc_deg: float = 0.0
    yaw_osc_period_s: float = 220.0
    episode_duration_s: float = 2700.0
    dt_rk4_s: float = 2.0
    noise_pos_m: float = 1.2
    noise_sog_kn: float = 0.04
    noise_cog_deg: float = 0.35
    noise_hdg_deg: float = 0.25


def _wrap_angle_rad(angle_rad: float) -> float:
    """Wrap angle in radians to (-pi, pi]."""
    return (angle_rad + math.pi) % (2.0 * math.pi) - math.pi


def _signed_diff_deg(heading_deg: float, cog_deg: float) -> float:
    """Compute signed angle (heading - cog) wrapped to (-180, 180] degrees."""
    return (heading_deg - cog_deg + 180.0) % 360.0 - 180.0


def catenary_seabed_drag(
    depth_m: float,
    chain_length_m: float,
    w_chain_nm: float,
    anchor_weight_t: float,
    eta_soil: float,
    stick_slip_xi: float = 0.0,
    hawsepipe_side: int = 1,
    lpp_m: float = 228.0,
    beam_m: float = 42.0,
    ramp_factor: float = 1.0,
) -> Tuple[float, float, float, float]:
    """Compute quasi-static catenary horizontal seabed tension and asymmetric hawsepipe moment.

    Implements DNV-RP-E301 seabed holding resistance coupled with quasi-static suspended
    catenary geometry and hawsepipe bow offset `(x_h = +0.47 * Lpp, y_h = +/-0.08 * B)`.
    When paid-out chain length `chain_length_m <= depth_m`, the anchor hangs above the
    seabed and exerts zero horizontal seabed drag force.

    Args:
        depth_m: Seabed water depth `h` in meters (`25-85 m`).
        chain_length_m: Paid-out anchor chain length `L_c` in meters (`6-11 shackles`).
        w_chain_nm: Submerged chain weight per unit length `w_c` in N/m.
        anchor_weight_t: Submerged anchor mass/weight `W_anchor` in metric tonnes (`12-16 t`).
        eta_soil: DNV-RP-E301 soil holding factor (`3.5` soft mud/clay to `8.5` glacial till).
        stick_slip_xi: Dimensionless Ornstein-Uhlenbeck + jump stick-slip state around `0.0`.
        hawsepipe_side: `+1` for starboard hawsepipe drop, `-1` for port hawsepipe drop.
        lpp_m: Vessel length between perpendiculars in meters (`228.0 m`).
        beam_m: Vessel beam in meters (`42.0 m`).
        ramp_factor: Deployment payout engagement factor in `[0.0, 1.0]`.

    Returns:
        4-tuple `(t_horiz_n, fx_anchor_n, fy_anchor_n, n_anchor_nm)` containing horizontal
        catenary tension `T_H(t)` (N), surge force `F_x` (N), sway force `F_y` (N), and
        yaw moment `N_anchor = x_h * F_y - y_h * F_x` (N*m).
    """
    if chain_length_m <= depth_m or depth_m <= 0.0 or ramp_factor <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)

    scope_ratio = chain_length_m / depth_m
    cos_scope = math.sqrt(max(0.0, 1.0 - 1.0 / (scope_ratio * scope_ratio)))

    w_anchor_n = float(anchor_weight_t) * 1000.0 * GRAVITY_MS2
    grounded_length_m = max(0.0, chain_length_m - 1.08 * depth_m)
    mu_chain_seabed = 0.72

    fluke_holding_n = float(eta_soil) * w_anchor_n * (0.55 + 0.45 * cos_scope)
    chain_friction_n = mu_chain_seabed * float(w_chain_nm) * grounded_length_m
    catenary_suspended_n = float(w_chain_nm) * depth_m * cos_scope / max(1.0 - cos_scope, 0.18)

    base_tension_n = (fluke_holding_n + chain_friction_n + 0.15 * catenary_suspended_n) * cos_scope
    modulation = max(0.45, min(1.75, 1.0 + float(stick_slip_xi)))
    t_horiz_n = float(ramp_factor) * base_tension_n * modulation

    side_sign = 1.0 if hawsepipe_side >= 0 else -1.0
    lead_angle_rad = math.radians(22.0) * side_sign
    fx_anchor_n = -t_horiz_n * math.cos(lead_angle_rad)
    fy_anchor_n = t_horiz_n * math.sin(lead_angle_rad)

    x_h = 0.47 * float(lpp_m)
    y_h = side_sign * 0.08 * float(beam_m)
    n_anchor_nm = x_h * fy_anchor_n - y_h * fx_anchor_n
    return (t_horiz_n, fx_anchor_n, fy_anchor_n, n_anchor_nm)


def _wind_loads(
    u_ms: float,
    v_ms: float,
    heading_rad: float,
    wind_speed_ms: float,
    wind_from_deg: float,
    params: TankerParams,
) -> Tuple[float, float, float]:
    """Compute aerodynamic surge force, sway force, and yaw moment in the vessel frame."""
    wind_to_rad = math.radians((wind_from_deg + 180.0) % 360.0)
    rel_angle = wind_to_rad - heading_rad
    u_rw = wind_speed_ms * math.cos(rel_angle) - u_ms
    v_rw = wind_speed_ms * math.sin(rel_angle) - v_ms
    v_rw_mag = math.hypot(u_rw, v_rw)
    if v_rw_mag < 1e-6:
        return (0.0, 0.0, 0.0)

    q_dyn = 0.5 * RHO_AIR_KGM3 * v_rw_mag
    fx_w = q_dyn * params.cx_wind * params.area_frontal_m2 * u_rw
    fy_w = q_dyn * params.cy_wind * params.area_lateral_m2 * v_rw
    n_w = q_dyn * params.cn_wind * params.area_lateral_m2 * params.lpp_m * v_rw
    return (fx_w, fy_w, n_w)


def simulate_episode(
    cfg: EpisodeConfig,
    params: TankerParams,
    rng: np.random.Generator,
) -> Tuple[List[Dict[str, Any]], Dict[str, np.ndarray]]:
    """Integrate the 3-DOF Fossen tanker ODE via RK4 and sample noisy Class-A AIS fixes.

    Args:
        cfg: Episode configuration specifying vessel regime, metocean state, and seabed parameters.
        params: Physical Aframax hull, rudder, and chain constants.
        rng: NumPy random generator for stochastic stick-slip and AIS sensor noise.

    Returns:
        Tuple `(ais_track, continuous_history)` where `ais_track` is a list of fix dicts
        compatible with `custody/indicators.py` and `continuous_history` stores full-rate
        NumPy arrays for diagnostic plotting and physics verification.
    """
    n_steps = int(round(cfg.episode_duration_s / cfg.dt_rk4_s)) + 1
    dt = float(cfg.dt_rk4_s)

    lat_deg = float(cfg.lat0_deg)
    lon_deg = float(cfg.lon0_deg)
    heading_ref_rad = math.radians(cfg.heading_ref_deg % 360.0)
    heading_rad = heading_ref_rad

    u_cruise_ms = float(cfg.u_cruise_kn) * KNOTS_TO_MS
    u_slow_ms = float(cfg.u_target_slow_kn) * KNOTS_TO_MS
    wind_speed_ms = float(cfg.wind_speed_kn) * KNOTS_TO_MS
    current_speed_ms = float(cfg.current_speed_kn) * KNOTS_TO_MS
    current_to_rad = math.radians(cfg.current_to_deg % 360.0)

    u_c0 = current_speed_ms * math.cos(current_to_rad - heading_rad)
    v_c0 = current_speed_ms * math.sin(current_to_rad - heading_rad)
    u_ms = u_cruise_ms
    v_ms = v_c0
    r_rads = 0.0
    int_err_rad = 0.0
    xi_ou = 0.0

    chain_length_m = float(cfg.chain_shackles) * SHACKLE_M
    mass_scale = params.mass_kg / 8.50e7

    t_arr = np.zeros(n_steps, dtype=np.float64)
    sog_arr = np.zeros(n_steps, dtype=np.float64)
    crab_arr = np.zeros(n_steps, dtype=np.float64)
    th_arr = np.zeros(n_steps, dtype=np.float64)
    rudder_arr = np.zeros(n_steps, dtype=np.float64)
    lat_arr = np.zeros(n_steps, dtype=np.float64)
    lon_arr = np.zeros(n_steps, dtype=np.float64)
    hdg_arr = np.zeros(n_steps, dtype=np.float64)
    cog_arr = np.zeros(n_steps, dtype=np.float64)

    def _thrust_and_anchor_at(
        t_sec: float,
        u_val: float,
        v_val: float,
        xi_val: float,
    ) -> Tuple[float, float, float, float, float]:
        """Compute engine propeller thrust and anchor catenary loads at time `t_sec`."""
        u_rel_cruise = max(1.0, u_cruise_ms - u_c0)
        thrust_cruise_n = params.c_xu_kgm * u_rel_cruise * u_rel_cruise

        if cfg.regime == "normal":
            kp_spd = 9.5e5 * mass_scale
            thrust_n = thrust_cruise_n + kp_spd * (u_cruise_ms - u_val)
            return (thrust_n, 0.0, 0.0, 0.0, 0.0)

        if cfg.regime == "benign_slowdown":
            if t_sec <= cfg.t_maneuver_s:
                u_cmd = u_cruise_ms
                kp_spd = 1.15e6 * mass_scale
            else:
                elapsed_man = t_sec - cfg.t_maneuver_s
                if cfg.slowdown_ramp_s < 200.0:
                    # Two-notch bridge telegraph step-down: Full Ahead -> Half Ahead -> Slow Ahead
                    if elapsed_man <= 185.0:
                        ramp1 = min(1.0, elapsed_man / 12.0)
                        u_cmd = u_cruise_ms - (1.42 * KNOTS_TO_MS) * ramp1
                    else:
                        u_stage1 = u_cruise_ms - 1.42 * KNOTS_TO_MS
                        decel_ms = (2.15 * KNOTS_TO_MS / 60.0) * (elapsed_man - 185.0)
                        u_cmd = max(u_slow_ms, u_stage1 - decel_ms)
                    kp_spd = 1.25e7 * mass_scale
                else:
                    frac = min(1.0, elapsed_man / max(cfg.slowdown_ramp_s, 1.0))
                    smooth = 0.5 * (1.0 - math.cos(math.pi * frac))
                    u_cmd = u_cruise_ms + smooth * (u_slow_ms - u_cruise_ms)
                    kp_spd = 1.15e6 * mass_scale
            u_rel_cmd = max(0.8, u_cmd - u_c0)
            thrust_n = params.c_xu_kgm * u_rel_cmd * u_rel_cmd + kp_spd * (u_cmd - u_val)
            return (max(0.0, thrust_n), 0.0, 0.0, 0.0, 0.0)

        if t_sec <= cfg.t_maneuver_s:
            kp_spd = 9.5e5 * mass_scale
            thrust_n = thrust_cruise_n + kp_spd * (u_cruise_ms - u_val)
            return (thrust_n, 0.0, 0.0, 0.0, 0.0)

        elapsed_drop = t_sec - cfg.t_maneuver_s
        ramp = min(1.0, elapsed_drop / max(cfg.slowdown_ramp_s, 1.0))
        t_h, fx_a, fy_a, n_a = catenary_seabed_drag(
            depth_m=cfg.depth_m,
            chain_length_m=chain_length_m,
            w_chain_nm=params.submerged_chain_w_nm,
            anchor_weight_t=cfg.anchor_weight_t,
            eta_soil=cfg.eta_soil,
            stick_slip_xi=xi_val,
            hawsepipe_side=cfg.hawsepipe_side,
            lpp_m=params.lpp_m,
            beam_m=params.beam_m,
            ramp_factor=ramp,
        )
        if t_h <= 0.0:
            kp_spd = 9.5e5 * mass_scale
            return (thrust_cruise_n + kp_spd * (u_cruise_ms - u_val), 0.0, 0.0, 0.0, 0.0)

        # Two-stage payout + fluke burial followed by DNV-RP-E301 stick-slip speed ripples
        if elapsed_drop <= 88.0:
            # Stage 1: chain paying out over hawsepipe / dragging on seabed (~1.05 kn gradual payout)
            ramp1 = min(1.0, elapsed_drop / 65.0)
            u_target_perturbed = u_cruise_ms - (1.05 * KNOTS_TO_MS) * ramp1
            plowing_gain = 1.0e7 * mass_scale
        elif elapsed_drop <= 185.0:
            # Stage 2: chain stopper taut, flukes bury deeply into clay/till (~2.8 kn/min braking)
            u_stage1 = u_cruise_ms - 1.05 * KNOTS_TO_MS
            decel_ms = (2.85 * KNOTS_TO_MS / 60.0) * (elapsed_drop - 88.0)
            u_target_perturbed = max(u_slow_ms, u_stage1 - decel_ms)
            plowing_gain = 1.4e7 * mass_scale
        else:
            # Stage 3: steady dragging with DNV-RP-E301 stick-slip cycles around u_slow_ms
            u_target_perturbed = max(
                (cfg.u_target_slow_kn - 0.72) * KNOTS_TO_MS,
                min(
                    (cfg.u_target_slow_kn + 0.74) * KNOTS_TO_MS,
                    u_slow_ms + (0.74 * KNOTS_TO_MS) * xi_val,
                ),
            )
            plowing_gain = 1.2e7 * mass_scale

        u_rel_target = max(1.2, u_target_perturbed - u_c0)
        steady_hull_n = params.c_xu_kgm * u_rel_target * u_rel_target + params.c_xvv_kgm * v_val * v_val
        plowing_braking_n = plowing_gain * (u_val - u_target_perturbed)
        thrust_n = steady_hull_n - fx_a - plowing_braking_n

        # Self-aligning hawsepipe lateral force scaled by DNV-RP-E301 soil factor eta_soil
        # Soft mud (eta=3.5 -> ~6.6 deg crab) vs glacial till (eta=8.5 -> ~14.2 deg crab)
        side_sign = 1.0 if cfg.hawsepipe_side >= 0 else -1.0
        ramp_lat = min(1.0, elapsed_drop / 35.0)
        eq_crab_deg = 6.5 + 1.52 * (cfg.eta_soil - 3.5) - 0.5 * xi_val
        target_v_ms = side_sign * max(1.5, u_val) * math.tan(math.radians(eq_crab_deg))
        fy_eff_n = fy_a + (2.40e6 * mass_scale) * ramp_lat * (target_v_ms - v_val)
        return (thrust_n, t_h, fx_a, fy_eff_n, n_a)

    def _rhs(
        t_sec: float,
        lat_d: float,
        lon_d: float,
        psi_r: float,
        u_val: float,
        v_val: float,
        r_val: float,
        i_err: float,
        xi_val: float,
    ) -> Tuple[float, float, float, float, float, float, float, float]:
        """Evaluate 3-DOF Fossen manoeuvring derivatives and PID rudder command."""
        u_c = current_speed_ms * math.cos(current_to_rad - psi_r)
        v_c = current_speed_ms * math.sin(current_to_rad - psi_r)
        u_r = u_val - u_c
        v_r = v_val - v_c
        u_tot = math.hypot(u_r, v_r) + 0.15

        psi_cmd = heading_ref_rad
        if cfg.yaw_osc_deg > 0.0:
            psi_cmd += math.radians(cfg.yaw_osc_deg) * math.sin(
                2.0 * math.pi * t_sec / max(cfg.yaw_osc_period_s, 30.0)
            )
        err_psi = _wrap_angle_rad(psi_cmd - psi_r)
        delta_cmd = (
            params.kp_rudder * err_psi
            - params.kd_rudder * r_val
            + params.ki_rudder * i_err
        )
        delta_rad = max(-params.max_rudder_rad, min(params.max_rudder_rad, delta_cmd))

        # Propeller slipstream inflow keeps rudder authority active while under engine power
        x_R = -0.48 * params.lpp_m
        q_rudder = max(u_tot * u_tot, 28.0)
        y_rudder_n = -params.c_ydelta_kgm * q_rudder * delta_rad
        x_rudder_n = -0.15 * abs(y_rudder_n * math.sin(delta_rad))
        n_rudder_nm = x_R * y_rudder_n

        x_hull_n = -params.c_xu_kgm * abs(u_r) * u_r - params.c_xvv_kgm * v_r * v_r
        y_hull_n = (
            -params.c_yv_kgm * u_tot * v_r
            - params.c_yvv_kgm * abs(v_r) * v_r
            - params.c_yr_kg * u_tot * r_val
        )
        n_hull_nm = (
            -params.c_nr_kgm * u_tot * r_val
            - params.c_nrr_kgm2 * abs(r_val) * r_val
            - params.c_nv_kg * u_tot * v_r
        )

        fx_w, fy_w, n_w = _wind_loads(
            u_val, v_val, psi_r, wind_speed_ms, cfg.wind_from_deg, params
        )
        thrust_n, _, fx_a, fy_a, n_a = _thrust_and_anchor_at(
            t_sec, u_val, v_val, xi_val
        )

        du_dt = (
            params.m_v_kg * v_r * r_val
            + thrust_n
            + x_hull_n
            + x_rudder_n
            + fx_w
            + fx_a
        ) / params.m_u_kg
        dv_dt = (
            -params.m_u_kg * u_r * r_val
            + y_hull_n
            + y_rudder_n
            + fy_w
            + fy_a
        ) / params.m_v_kg
        dr_dt = (n_hull_nm + n_rudder_nm + n_w + n_a) / params.i_r_kgm2

        v_north_ms = u_val * math.cos(psi_r) - v_val * math.sin(psi_r)
        v_east_ms = u_val * math.sin(psi_r) + v_val * math.cos(psi_r)
        dlat_dt = v_north_ms / custody_geo.M_PER_DEG_LAT
        dlon_dt = v_east_ms / custody_geo.m_per_deg_lon(lat_d)

        return (dlat_dt, dlon_dt, r_val, du_dt, dv_dt, dr_dt, err_psi, delta_rad)

    tau_ou_s = 18.0
    sigma_ou = 0.14
    jump_rate_per_s = 1.0 / 55.0

    for idx in range(n_steps):
        t_sec = idx * dt
        t_arr[idx] = t_sec

        _, t_h_now, _, _, _ = _thrust_and_anchor_at(t_sec, u_ms, v_ms, xi_ou)
        _, _, _, _, _, _, _, delta_now = _rhs(
            t_sec, lat_deg, lon_deg, heading_rad, u_ms, v_ms, r_rads, int_err_rad, xi_ou
        )

        v_north_ms = u_ms * math.cos(heading_rad) - v_ms * math.sin(heading_rad)
        v_east_ms = u_ms * math.sin(heading_rad) + v_ms * math.cos(heading_rad)
        sog_kn = math.hypot(v_east_ms, v_north_ms) * MS_TO_KNOTS
        cog_deg = math.degrees(math.atan2(v_east_ms, v_north_ms)) % 360.0
        hdg_deg = math.degrees(heading_rad) % 360.0

        sog_arr[idx] = sog_kn
        crab_arr[idx] = _signed_diff_deg(hdg_deg, cog_deg)
        th_arr[idx] = t_h_now / 1e3  # kN
        rudder_arr[idx] = math.degrees(delta_now)
        lat_arr[idx] = lat_deg
        lon_arr[idx] = lon_deg
        hdg_arr[idx] = hdg_deg
        cog_arr[idx] = cog_deg

        if idx == n_steps - 1:
            break

        k1 = _rhs(t_sec, lat_deg, lon_deg, heading_rad, u_ms, v_ms, r_rads, int_err_rad, xi_ou)
        k2 = _rhs(
            t_sec + 0.5 * dt,
            lat_deg + 0.5 * dt * k1[0],
            lon_deg + 0.5 * dt * k1[1],
            heading_rad + 0.5 * dt * k1[2],
            u_ms + 0.5 * dt * k1[3],
            v_ms + 0.5 * dt * k1[4],
            r_rads + 0.5 * dt * k1[5],
            int_err_rad + 0.5 * dt * k1[6],
            xi_ou,
        )
        k3 = _rhs(
            t_sec + 0.5 * dt,
            lat_deg + 0.5 * dt * k2[0],
            lon_deg + 0.5 * dt * k2[1],
            heading_rad + 0.5 * dt * k2[2],
            u_ms + 0.5 * dt * k2[3],
            v_ms + 0.5 * dt * k2[4],
            r_rads + 0.5 * dt * k2[5],
            int_err_rad + 0.5 * dt * k2[6],
            xi_ou,
        )
        k4 = _rhs(
            t_sec + dt,
            lat_deg + dt * k3[0],
            lon_deg + dt * k3[1],
            heading_rad + dt * k3[2],
            u_ms + dt * k3[3],
            v_ms + dt * k3[4],
            r_rads + dt * k3[5],
            int_err_rad + dt * k3[6],
            xi_ou,
        )

        lat_deg += (dt / 6.0) * (k1[0] + 2.0 * k2[0] + 2.0 * k3[0] + k4[0])
        lon_deg += (dt / 6.0) * (k1[1] + 2.0 * k2[1] + 2.0 * k3[1] + k4[1])
        heading_rad += (dt / 6.0) * (k1[2] + 2.0 * k2[2] + 2.0 * k3[2] + k4[2])
        u_ms = max(0.3, u_ms + (dt / 6.0) * (k1[3] + 2.0 * k2[3] + 2.0 * k3[3] + k4[3]))
        v_ms += (dt / 6.0) * (k1[4] + 2.0 * k2[4] + 2.0 * k3[4] + k4[4])
        r_rads += (dt / 6.0) * (k1[5] + 2.0 * k2[5] + 2.0 * k3[5] + k4[5])
        int_err_rad = max(
            -8.0,
            min(8.0, int_err_rad + (dt / 6.0) * (k1[6] + 2.0 * k2[6] + 2.0 * k3[6] + k4[6])),
        )

        if cfg.regime == "anchor_drag" and t_sec >= cfg.t_maneuver_s and chain_length_m > cfg.depth_m:
            elapsed_post = t_sec - cfg.t_maneuver_s
            # Asymmetric DNV-RP-E301 stick-slip: 170s slip plateau then 92s stick bite trough
            if elapsed_post < 185.0:
                stick_slip_wave = 0.95
                tau_eff = 6.0
            else:
                cycle_period_s = 262.0
                phase = ((elapsed_post - 185.0) % cycle_period_s) / cycle_period_s
                if phase < 0.65:
                    stick_slip_wave = 0.98
                    tau_eff = 5.0
                else:
                    stick_slip_wave = -0.98
                    tau_eff = 3.5
            d_xi = (
                ((stick_slip_wave - xi_ou) / tau_eff) * dt
                + 0.03 * math.sqrt(dt / tau_ou_s) * float(rng.normal())
            )
            if float(rng.random()) < jump_rate_per_s * dt:
                d_xi += float(rng.choice([-0.06, 0.06])) * float(rng.uniform(0.7, 1.1))
            xi_ou = max(-1.05, min(1.05, xi_ou + d_xi))
        else:
            xi_ou = 0.0

    sample_times_s: List[float] = [0.0]
    cur_t = 0.0
    while True:
        step_s = float(rng.uniform(61.0, 86.0))
        if cur_t + step_s >= cfg.episode_duration_s:
            rem = cfg.episode_duration_s - cur_t
            if rem >= 60.5:
                sample_times_s.append(cfg.episode_duration_s)
            break
        cur_t += step_s
        sample_times_s.append(cur_t)

    ais_track: List[Dict[str, Any]] = []
    for t_samp in sample_times_s:
        idx_near = min(n_steps - 1, max(0, int(round(t_samp / dt))))
        lat_n = float(lat_arr[idx_near]) + (
            float(rng.normal(0.0, cfg.noise_pos_m)) / custody_geo.M_PER_DEG_LAT
        )
        lon_n = float(lon_arr[idx_near]) + (
            float(rng.normal(0.0, cfg.noise_pos_m))
            / custody_geo.m_per_deg_lon(float(lat_arr[idx_near]))
        )
        sog_n = max(
            0.1,
            float(sog_arr[idx_near]) + float(rng.normal(0.0, cfg.noise_sog_kn)),
        )
        cog_n = (float(cog_arr[idx_near]) + float(rng.normal(0.0, cfg.noise_cog_deg))) % 360.0
        hdg_n = (float(hdg_arr[idx_near]) + float(rng.normal(0.0, cfg.noise_hdg_deg))) % 360.0
        ts_ms = BASE_EPOCH_MS + int(round(t_samp * 1000.0))
        ais_track.append(
            {
                "mmsi": cfg.mmsi,
                "ts": ts_ms,
                "lat": round(lat_n, 6),
                "lon": round(lon_n, 6),
                "sog": round(sog_n, 2),
                "cog": round(cog_n, 1),
                "heading": round(hdg_n, 1),
                "navStat": 0,
                "shipType": cfg.ship_type,
                "src_file": "sim_anchor_drag_rk4",
            }
        )

    history = {
        "t_min": t_arr / 60.0,
        "sog_kn": sog_arr,
        "crab_deg": crab_arr,
        "tension_kn": th_arr,
        "rudder_deg": rudder_arr,
        "lat_deg": lat_arr,
        "lon_deg": lon_arr,
    }
    return (ais_track, history)


def build_corridor_index() -> custody_geo.SegmentIndex:
    """Build a synthetic Estlink-2 / Gulf of Finland trunk cable polyline index around (59.85°N, 25.50°E)."""
    idx = custody_geo.SegmentIndex()
    heading_rad = math.radians(78.0)
    lat_center = 59.85
    lon_center = 25.50
    for offset_m, name, kind, osm_id in (
        (0.0, "Estlink-2 Subsea HVDC Corridor", "cable", "estlink2_trunk"),
        (1100.0, "C-Lion1 Telecom Trunk", "cable", "clion1_trunk"),
        (-1100.0, "Balticconnector Gas Pipeline", "pipeline", "balticconnector"),
    ):
        dlat_off = (offset_m * math.cos(heading_rad + math.pi / 2.0)) / custody_geo.M_PER_DEG_LAT
        dlon_off = (offset_m * math.sin(heading_rad + math.pi / 2.0)) / custody_geo.m_per_deg_lon(
            lat_center
        )
        pts: List[Tuple[float, float]] = []
        for s_km in np.linspace(-18.0, 28.0, 24):
            s_m = float(s_km) * 1000.0
            lat_p = lat_center + dlat_off + (s_m * math.cos(heading_rad)) / custody_geo.M_PER_DEG_LAT
            lon_p = lon_center + dlon_off + (s_m * math.sin(heading_rad)) / custody_geo.m_per_deg_lon(
                lat_center
            )
            pts.append((lon_p, lat_p))
        idx.add_polyline(pts, (name, kind, osm_id))
    return idx


def generate_dataset(
    n_per_class: int = 500,
    seed: int = 42,
) -> Tuple[List[Tuple[EpisodeConfig, List[Dict[str, Any]], Dict[str, np.ndarray]]], VesselHullParams]:
    """Generate `3 * n_per_class` simulated Gulf of Finland multi-hull tracks across the 3 regimes.

    Cycles evenly across 3 hull profiles (`aframax_tanker`, `mariner_cargo`, `coastal_feeder`),
    with random port/starboard hawsepipe drops, water depths `20-140 m` (including deep water
    `> 115 m` negative examples where the anchor hangs above seabed), wind `5-28 kn`, and soil
    factors `3.5-8.5`.
    """
    rng = np.random.default_rng(seed)
    hull_names = ("aframax_tanker", "mariner_cargo", "coastal_feeder")
    dataset: List[Tuple[EpisodeConfig, List[Dict[str, Any]], Dict[str, np.ndarray]]] = []

    regimes = ("normal", "benign_slowdown", "anchor_drag")
    for r_idx, regime in enumerate(regimes):
        for i in range(n_per_class):
            hull_name = hull_names[i % len(hull_names)]
            params = HULL_PROFILES[hull_name]
            mmsi = 276100000 + r_idx * 1000 + i
            lat0 = 59.85 + float(rng.uniform(-0.009, 0.009))
            lon0 = 25.50 + float(rng.uniform(-0.015, 0.015))
            hdg_ref = float(rng.uniform(73.0, 83.0))
            wind_kn = float(rng.uniform(5.0, 28.0))
            wind_from = float(rng.uniform(0.0, 360.0))
            curr_kn = float(rng.uniform(0.0, 0.6))
            curr_to = float(rng.uniform(0.0, 360.0))
            w_anc = float(rng.uniform(params.anchor_weight_min_t, params.anchor_weight_max_t))
            eta = float(rng.uniform(3.5, 8.5))
            side = int(rng.choice([-1, 1]))

            if regime == "normal":
                u_cruise = float(rng.uniform(params.cruise_min_kn, params.cruise_max_kn))
                u_slow = u_cruise
                t_man = 600.0
                ramp_s = 300.0
                if i % 5 == 0:
                    depth_m = float(rng.uniform(116.0, 140.0))
                    shackles = float(rng.uniform(2.5, 4.0)) if (i % 10 == 0) else 0.0
                else:
                    depth_m = float(rng.uniform(20.0, 115.0))
                    shackles = 0.0
            elif regime == "benign_slowdown":
                u_cruise = float(rng.uniform(max(10.5, params.cruise_min_kn), params.cruise_max_kn))
                if (i % 4) == 0:
                    # Two-notch telegraph step-down (strong deceleration without anchor contact)
                    t_man = float(rng.uniform(240.0, 380.0))
                    u_slow = float(rng.uniform(4.25, 5.60))
                    ramp_s = float(rng.uniform(110.0, 175.0))
                else:
                    # Smooth gradual engine throttle reduction
                    t_man = float(rng.uniform(420.0, 620.0))
                    u_slow = float(rng.uniform(5.10, 8.20))
                    ramp_s = float(rng.uniform(260.0, 560.0))
                if (i % 5) == 0:
                    # Deep water (> 115 m) where a lowered anchor (3-4 shackles) hangs above seabed
                    depth_m = float(rng.uniform(116.0, 140.0))
                    shackles = float(rng.uniform(2.5, 4.0))
                else:
                    depth_m = float(rng.uniform(20.0, 115.0))
                    shackles = 0.0
            else:
                u_cruise = float(rng.uniform(params.cruise_min_kn, params.cruise_max_kn))
                t_man = 600.0  # t_drop = 10.0 min
                ramp_s = float(rng.uniform(85.0, 115.0))
                depth_m = float(rng.uniform(20.0, 105.0))
                min_shackles = max(6.0, (depth_m / SHACKLE_M) + 1.8)
                shackles = float(rng.uniform(min_shackles, max(min_shackles + 1.0, 12.0)))
                if eta < 4.25:
                    u_slow = float(rng.uniform(4.25, 4.65))
                else:
                    u_slow = float(rng.uniform(3.75, 4.18))

            cfg = EpisodeConfig(
                mmsi=mmsi,
                regime=regime,
                lat0_deg=lat0,
                lon0_deg=lon0,
                heading_ref_deg=hdg_ref,
                u_cruise_kn=u_cruise,
                u_target_slow_kn=u_slow,
                t_maneuver_s=t_man,
                slowdown_ramp_s=ramp_s,
                wind_speed_kn=wind_kn,
                wind_from_deg=wind_from,
                current_speed_kn=curr_kn,
                current_to_deg=curr_to,
                depth_m=depth_m,
                chain_shackles=shackles,
                anchor_weight_t=w_anc,
                eta_soil=eta,
                hawsepipe_side=side,
                hull_class=hull_name,
                ship_type=params.ship_type,
                yaw_osc_deg=(
                    float(rng.uniform(4.5, 11.0))
                    if (regime != "anchor_drag" and (i % 2) == 1)
                    else 0.0
                ),
                yaw_osc_period_s=float(rng.uniform(160.0, 260.0)),
            )
            track, hist = simulate_episode(cfg, params, rng)
            dataset.append((cfg, track, hist))

    return (dataset, HULL_PROFILES["aframax_tanker"])


def compute_seabed_reachable(depth_m: Optional[float]) -> float:
    """Map seabed depth (m) to anchor reachability: 1.0 in [10,110], 0.0 if >120 or <10, 0.5 if unknown."""
    if depth_m is None or not math.isfinite(float(depth_m)):
        return 0.5
    d = float(depth_m)
    if 10.0 <= d <= 110.0:
        return 1.0
    if 110.0 < d <= 120.0:
        return (120.0 - d) / 10.0
    return 0.0


def _build_ind08_kept_and_jumps(
    track: Sequence[Dict[str, Any]],
    th: Optional[Dict[str, Any]] = None,
) -> Tuple[set, List[Tuple[int, Dict[str, Any]]]]:
    """Build IND-07 raw jump indices and downsampled `kept` fixes identically to `custody/indicators.py`."""
    th = th or custody_ind.THRESHOLDS
    min_dt = float(th.get("motion_min_dt_s", custody_motion.VALID_DT_MIN_S))
    min_sog = float(th.get("motion_min_sog_kn", custody_motion.VALID_SOG_MIN_KN))
    max_sog = float(th.get("motion_max_sog_kn", custody_motion.VALID_SOG_MAX_KN))
    max_plausible_kn = float(th.get("impossible_kn", 45.0))
    imp_min_dt_s = float(th.get("impossible_min_dt_s", 5.0))
    imp_min_dist_m = float(th.get("impossible_min_dist_m", 2000.0))

    jump_raw_indices = set()
    for i in range(len(track) - 1):
        fa, fb = track[i], track[i + 1]
        try:
            lon_a, lat_a, ts_a = float(fa["lon"]), float(fa["lat"]), float(fa["ts"])
            lon_b, lat_b, ts_b = float(fb["lon"]), float(fb["lat"]), float(fb["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (
            math.isfinite(lon_a)
            and math.isfinite(lat_a)
            and math.isfinite(ts_a)
            and math.isfinite(lon_b)
            and math.isfinite(lat_b)
            and math.isfinite(ts_b)
        ):
            continue
        dt_raw = (ts_b - ts_a) / 1000.0
        if dt_raw < imp_min_dt_s:
            continue
        d_raw = custody_geo.haversine_m(lon_a, lat_a, lon_b, lat_b)
        if d_raw >= imp_min_dist_m and (d_raw / dt_raw) * 1.9438445 > max_plausible_kn:
            jump_raw_indices.add(i)
            jump_raw_indices.add(i + 1)

    kept: List[Tuple[int, Dict[str, Any]]] = []
    for idx, f in enumerate(track):
        lon, lat, sog, ts = f.get("lon"), f.get("lat"), f.get("sog"), f.get("ts")
        if lon is None or lat is None or sog is None or ts is None:
            continue
        try:
            lon_val = float(lon)
            lat_val = float(lat)
            sog_val = float(sog)
            ts_val = float(ts)
        except (TypeError, ValueError):
            continue
        if not (
            math.isfinite(lon_val)
            and math.isfinite(lat_val)
            and math.isfinite(sog_val)
            and math.isfinite(ts_val)
        ):
            continue
        if f.get("navStat") in (1, 5):
            continue
        if not (min_sog < sog_val < max_sog):
            continue
        if not kept or (ts_val - float(kept[-1][1]["ts"])) / 1000.0 >= min_dt:
            kept.append((idx, f))

    return (jump_raw_indices, kept)


def compute_window_crab_features(
    track: Sequence[Dict[str, Any]],
    peak_idx_end: int,
    half_window: int = 3,
) -> Tuple[float, float]:
    """Compute `(unilateral_crab_deg, crab_sign_consistency)` over `+-half_window` fixes around `peak_idx_end`."""
    lo = max(0, int(peak_idx_end) - half_window)
    hi = min(len(track), int(peak_idx_end) + half_window + 1)
    diffs: List[float] = []
    for f in track[lo:hi]:
        hdg = f.get("heading")
        cog = f.get("cog")
        if hdg is None or cog is None:
            continue
        try:
            h_val = float(hdg)
            c_val = float(cog)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(h_val) and math.isfinite(c_val)):
            continue
        if h_val < 0.0 or h_val >= 360.0 or c_val < 0.0 or c_val >= 360.0:
            continue
        diffs.append(_signed_diff_deg(h_val, c_val))
    if not diffs:
        return (0.0, 0.0)
    unilateral_crab_deg = float(statistics.median(abs(d) for d in diffs))
    pos = sum(1 for d in diffs if d > 0.0)
    neg = sum(1 for d in diffs if d < 0.0)
    crab_sign_consistency = max(pos, neg) / float(len(diffs))
    return (unilateral_crab_deg, crab_sign_consistency)


def compute_step_mlp_timeline(
    track: Sequence[Dict[str, Any]],
    model: Dict[str, Any],
    return_steps: bool = False,
    corridor_idx: Any = None,
    th: Optional[Dict[str, Any]] = None,
    ship_type: Any = None,
) -> Any:
    """Evaluate `mlp_infer.predict` and `anomaly_score` identically to `custody/indicators.py:ind08_motion_anomaly`."""
    th = th or custody_ind.THRESHOLDS
    min_dt = float(th.get("motion_min_dt_s", custody_motion.VALID_DT_MIN_S))
    max_dt = float(th.get("motion_max_dt_s", custody_motion.VALID_DT_MAX_S))
    min_sog = float(th.get("motion_min_sog_kn", custody_motion.VALID_SOG_MIN_KN))
    max_sog = float(th.get("motion_max_sog_kn", custody_motion.VALID_SOG_MAX_KN))
    z_thresh = float(th.get("motion_radial_z", custody_motion.RADIAL_Z_95CI))
    min_dv = float(th.get("motion_min_dv_kn", 1.0))
    min_decel = float(th.get("motion_min_decel_kn", 0.8))
    max_corridor_m = float(th.get("motion_corridor_m", 5000.0))
    max_plausible_kn = float(th.get("impossible_kn", 45.0))

    resolved_ship_type = ship_type
    if resolved_ship_type is None and track:
        for f_item in track:
            st_cand = f_item.get("shipType")
            if st_cand is None:
                st_cand = f_item.get("ship_type")
            if st_cand is not None:
                resolved_ship_type = st_cand
                break
    is_maneuver = mlp_infer.is_maneuver_vessel_type(resolved_ship_type)

    jump_raw_indices, kept = _build_ind08_kept_and_jumps(track, th)
    if len(kept) < 3:
        if return_steps:
            return ([], [], [], [], [])
        return ([], [], [], [])

    two_pi = 2.0 * math.pi
    segs: List[Dict[str, Any]] = []
    for k in range(len(kept) - 1):
        idx0, f0 = kept[k]
        idx1, f1 = kept[k + 1]
        dt_s = (float(f1["ts"]) - float(f0["ts"])) / 1000.0
        sog0 = float(f0["sog"])
        sog1 = float(f1["sog"])
        in_domain = custody_motion.check_domain(
            dt_s,
            sog1,
            min_dt_s=min_dt,
            max_dt_s=max_dt,
            min_sog_kn=min_sog,
            max_sog_kn=max_sog,
        )
        lat0, lon0 = float(f0["lat"]), float(f0["lon"])
        lat1, lon1 = float(f1["lat"]), float(f1["lon"])
        dlat_nm = (lat1 - lat0) * 60.0
        dlon_nm = (lon1 - lon0) * 60.0 * math.cos(math.radians(0.5 * (lat0 + lat1)))
        dist_nm = math.hypot(dlon_nm, dlat_nm)
        disp_sog = dist_nm / max(dt_s / 3600.0, 1e-6)
        cog_raw = f1.get("cog")
        cog_val: Optional[float] = None
        if cog_raw is not None:
            try:
                c_f = float(cog_raw)
                if math.isfinite(c_f):
                    cog_val = c_f
            except (TypeError, ValueError):
                cog_val = None
        if dist_nm < 1e-6 and cog_val is not None:
            bearing_rad = math.radians(cog_val % 360.0)
        else:
            bearing_rad = math.atan2(dlon_nm, dlat_nm) % two_pi
        v_east = sog1 * math.sin(bearing_rad)
        v_north = sog1 * math.cos(bearing_rad)
        overlaps_jump = any(
            r_idx in jump_raw_indices for r_idx in range(idx0, idx1 + 1)
        )
        segs.append(
            {
                "idx0": idx0,
                "idx1": idx1,
                "kept_idx_end": k + 1,
                "f0": f0,
                "f1": f1,
                "dt_s": dt_s,
                "sog0": sog0,
                "sog1": sog1,
                "disp_sog": disp_sog,
                "in_domain": in_domain and (disp_sog <= max_plausible_kn) and not overlaps_jump,
                "bearing_rad": bearing_rad,
                "v_east": v_east,
                "v_north": v_north,
            }
        )

    t_mins: List[float] = []
    rz_all: List[float] = []
    rz_braking: List[float] = []
    hit_indices: List[int] = []
    step_details: List[Dict[str, Any]] = []

    for j in range(len(segs) - 1):
        s_prev = segs[j]
        s_curr = segs[j + 1]
        if not (s_prev["in_domain"] and s_curr["in_domain"]):
            continue

        sog_before = float(s_prev["sog1"])
        sog_after = float(s_curr["sog1"])
        if abs(s_prev["disp_sog"] - sog_before) >= 2.5:
            continue
        if (
            s_curr["disp_sog"] > max_plausible_kn
            or s_curr["disp_sog"] > max(sog_before, sog_after) * 1.8 + 3.0
            or abs(s_curr["disp_sog"] - sog_after) >= 2.5
        ):
            continue

        v_east0 = float(s_prev["v_east"])
        v_north0 = float(s_prev["v_north"])
        b_rad = float(s_prev["bearing_rad"])

        v_east1 = float(s_curr["v_east"])
        v_north1 = float(s_curr["v_north"])
        dt_s = float(s_curr["dt_s"])

        actual_dv_east = v_east1 - v_east0
        actual_dv_north = v_north1 - v_north0
        dv_kn = math.hypot(actual_dv_east, actual_dv_north)

        fb_dsog = max(-2.5, min(2.5, sog_before - float(s_prev["sog0"])))
        fb_prev_dve = fb_dsog * math.sin(b_rad)
        fb_prev_dvn = fb_dsog * math.cos(b_rad)
        if (
            j > 0
            and segs[j - 1]["in_domain"]
            and abs(segs[j - 1]["disp_sog"] - float(segs[j - 1]["sog1"])) < 2.5
        ):
            raw_prev_dve = v_east0 - float(segs[j - 1]["v_east"])
            raw_prev_dvn = v_north0 - float(segs[j - 1]["v_north"])
            if math.hypot(raw_prev_dve, raw_prev_dvn) < 2.5:
                prev_dv_east = raw_prev_dve
                prev_dv_north = raw_prev_dvn
            else:
                prev_dv_east = fb_prev_dve
                prev_dv_north = fb_prev_dvn
        else:
            prev_dv_east = fb_prev_dve
            prev_dv_north = fb_prev_dvn

        f_prev = s_curr["f0"]
        flow_dve, flow_dvn, has_flow = mlp_infer.lookup_flow(
            float(f_prev["lat"]), float(f_prev["lon"]), v_east0, v_north0, model
        )
        feat_map = {
            "v_east": v_east0,
            "v_north": v_north0,
            "sog": sog_before,
            "dt": dt_s,
            "wind_along": 0.0,
            "wind_cross": 0.0,
            "current_along": 0.0,
            "current_cross": 0.0,
            "prev_dv_east": prev_dv_east,
            "prev_dv_north": prev_dv_north,
            "is_maneuver_vessel": is_maneuver,
            "flow_dv_east": flow_dve,
            "flow_dv_north": flow_dvn,
            "has_flow": has_flow,
        }
        pred = mlp_infer.predict(feat_map, model_data=model)
        _, _, radial_z, _, is_anom = mlp_infer.anomaly_score(
            actual_dv_east, actual_dv_north, pred, z_threshold_95ci=z_thresh
        )
        t_step = (float(s_curr["f1"]["ts"]) - float(track[0]["ts"])) / 60000.0
        t_mins.append(t_step)
        rz_all.append(radial_z)

        decel_kn = sog_before - sog_after
        if decel_kn >= 0.4:
            rz_braking.append(radial_z * min(1.0, decel_kn / 0.8))
        else:
            rz_braking.append(0.0)

        in_corridor = True
        if corridor_idx is not None:
            f_end = s_curr["f1"]
            dist_m, payload = corridor_idx.nearest(f_end["lon"], f_end["lat"])
            in_corridor = (
                dist_m is not None and payload is not None and dist_m <= max_corridor_m
            )

        is_hit = bool(is_anom and dv_kn >= min_dv and decel_kn >= min_decel and in_corridor)
        if is_hit:
            hit_indices.append(int(s_curr["idx1"]))

        step_details.append(
            {
                "idx_end": int(s_curr["idx1"]),
                "kept_idx_end": int(s_curr["kept_idx_end"]),
                "radial_z": float(radial_z),
                "sog_before": float(sog_before),
                "sog_after": float(sog_after),
                "decel_kn": float(decel_kn),
                "dv_kn": float(dv_kn),
                "is_hit": is_hit,
            }
        )

    if return_steps:
        return (t_mins, rz_all, rz_braking, hit_indices, step_details)
    return (t_mins, rz_all, rz_braking, hit_indices)


def extract_tier2_features(
    cfg: EpisodeConfig,
    track: Sequence[Dict[str, Any]],
    step_details: Sequence[Dict[str, Any]],
    th: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Extract the 5 AIS+depth Tier-2 observable features over the braking/anomalous window."""
    if not step_details:
        return {
            "peak_radial_z_capped": 0.0,
            "braking_kn": 0.0,
            "unilateral_crab_deg": 0.0,
            "crab_sign_consistency": 0.0,
            "seabed_reachable": compute_seabed_reachable(cfg.depth_m),
        }

    hit_steps = [s for s in step_details if s["is_hit"]]
    if hit_steps:
        peak_step = max(hit_steps, key=lambda s: s["radial_z"])
    else:
        braking_steps = [s for s in step_details if s["decel_kn"] >= 0.4]
        pool = braking_steps if braking_steps else list(step_details)
        peak_step = max(pool, key=lambda s: s["radial_z"])

    peak_rz = float(peak_step["radial_z"])
    braking_kn = max(0.0, float(peak_step["sog_before"]) - float(peak_step["sog_after"]))
    _, kept = _build_ind08_kept_and_jumps(track, th)
    kept_fixes = [f for _, f in kept]
    unilateral_crab_deg, crab_sign_consistency = compute_window_crab_features(
        kept_fixes, int(peak_step["kept_idx_end"]), half_window=3
    )
    seabed_reachable = compute_seabed_reachable(cfg.depth_m)

    return {
        "peak_radial_z_capped": min(peak_rz, 50.0),
        "braking_kn": braking_kn,
        "unilateral_crab_deg": unilateral_crab_deg,
        "crab_sign_consistency": crab_sign_consistency,
        "seabed_reachable": seabed_reachable,
    }


def _sigmoid_np(z: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid in NumPy."""
    z_clip = np.clip(z, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-z_clip))


def stratified_train_test_split(
    records: Sequence[Dict[str, Any]],
    test_frac: float = 0.30,
    seed: int = 42,
) -> Tuple[List[int], List[int]]:
    """Split episode indices `70% train / 30% test` strictly stratified by `(regime, hull_class)`."""
    rng = np.random.default_rng(seed)
    strata: Dict[Tuple[str, str], List[int]] = {}
    for idx, rec in enumerate(records):
        key = (str(rec["regime"]), str(rec["cfg"].hull_class))
        strata.setdefault(key, []).append(idx)

    train_idx: List[int] = []
    test_idx: List[int] = []
    for key in sorted(strata):
        idxs = list(strata[key])
        rng.shuffle(idxs)
        n_test = max(1, int(round(len(idxs) * test_frac)))
        test_idx.extend(idxs[:n_test])
        train_idx.extend(idxs[n_test:])
    return (sorted(train_idx), sorted(test_idx))


def train_tier2_logreg(
    X_train: np.ndarray,
    y_train: np.ndarray,
    l2_reg: float = 1.0,
    max_iter: int = 50,
    tol: float = 1e-11,
) -> Dict[str, Any]:
    """Train a calibrated L2-regularized Logistic Regression in pure NumPy via Newton-Raphson IRLS."""
    mean = np.mean(X_train, axis=0)
    std = np.std(X_train, axis=0)
    std = np.where(std > 1e-8, std, 1.0)
    Xs = (X_train - mean) / std

    n_samples, n_features = Xs.shape
    X_aug = np.hstack([Xs, np.ones((n_samples, 1), dtype=np.float64)])
    theta = np.zeros(n_features + 1, dtype=np.float64)
    reg_diag = np.zeros(n_features + 1, dtype=np.float64)
    reg_diag[:n_features] = float(l2_reg)
    R = np.diag(reg_diag)

    for _ in range(max_iter):
        p = _sigmoid_np(X_aug @ theta)
        grad = X_aug.T @ (p - y_train) + R @ theta
        if float(np.max(np.abs(grad))) < tol:
            break
        s = np.clip(p * (1.0 - p), 1e-12, 0.25)
        H = (X_aug * s[:, None]).T @ X_aug + R
        delta = np.linalg.solve(H, grad)
        theta -= delta
        if float(np.max(np.abs(delta))) < tol:
            break

    weights = [float(v) for v in theta[:n_features]]
    bias = float(theta[n_features])
    return {
        "model_name": "AnchorDragTier2LogReg",
        "provenance": TIER2_PROVENANCE,
        "feature_names": list(TIER2_FEATURE_NAMES),
        "scaler": {
            "mean": [float(v) for v in mean],
            "std": [float(v) for v in std],
        },
        "weights": weights,
        "bias": bias,
        "thresholds": dict(TIER2_THRESHOLDS),
    }


def score_tier2_numpy(X: np.ndarray, tier2_model: Dict[str, Any]) -> np.ndarray:
    """Evaluate Tier-2 logistic regression probabilities on feature matrix `X`."""
    mean = np.asarray(tier2_model["scaler"]["mean"], dtype=np.float64)
    std = np.asarray(tier2_model["scaler"]["std"], dtype=np.float64)
    w = np.asarray(tier2_model["weights"], dtype=np.float64)
    b = float(tier2_model["bias"])
    Xs = (X - mean) / std
    return _sigmoid_np(Xs @ w + b)


def tier2_band(prob: float, thresholds: Optional[Dict[str, float]] = None) -> str:
    """Map probability to `HIGH` / `MODERATE` / `LOW`."""
    th = thresholds or TIER2_THRESHOLDS
    if prob >= float(th["high"]):
        return "HIGH"
    if prob >= float(th["moderate"]):
        return "MODERATE"
    return "LOW"


def export_dataset_csv(
    records: Sequence[Dict[str, Any]],
    output_path: str = DEFAULT_DATASET_PATH,
) -> str:
    """Export tabular 1,500-episode Tier-2 dataset to CSV."""
    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    fieldnames = [
        "mmsi",
        "regime",
        "label",
        "hull_class",
        "depth_m",
        "anchor_weight_t",
        "chain_shackles",
        "eta_soil",
        "wind_speed_kn",
        "hawsepipe_side",
        "split",
        *TIER2_FEATURE_NAMES,
        "fired_ind08",
        "tier2_prob",
        "tier2_band",
    ]
    with open(abs_out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            cfg: EpisodeConfig = rec["cfg"]
            feats: Dict[str, float] = rec["tier2_features"]
            writer.writerow(
                {
                    "mmsi": cfg.mmsi,
                    "regime": cfg.regime,
                    "label": 1 if cfg.regime == "anchor_drag" else 0,
                    "hull_class": cfg.hull_class,
                    "depth_m": round(cfg.depth_m, 2),
                    "anchor_weight_t": round(cfg.anchor_weight_t, 2),
                    "chain_shackles": round(cfg.chain_shackles, 2),
                    "eta_soil": round(cfg.eta_soil, 2),
                    "wind_speed_kn": round(cfg.wind_speed_kn, 2),
                    "hawsepipe_side": cfg.hawsepipe_side,
                    "split": rec["split"],
                    "peak_radial_z_capped": round(feats["peak_radial_z_capped"], 6),
                    "braking_kn": round(feats["braking_kn"], 6),
                    "unilateral_crab_deg": round(feats["unilateral_crab_deg"], 6),
                    "crab_sign_consistency": round(feats["crab_sign_consistency"], 6),
                    "seabed_reachable": round(feats["seabed_reachable"], 6),
                    "fired_ind08": int(bool(rec["fired_IND-08"])),
                    "tier2_prob": round(float(rec["score_Tier2"]), 6),
                    "tier2_band": rec["tier2_band"],
                }
            )
    return abs_out


def export_tier2_weights(
    tier2_model: Dict[str, Any],
    records: Sequence[Dict[str, Any]],
    ml_weights_path: str = DEFAULT_TIER2_WEIGHTS_PATH,
    custody_weights_path: str = DEFAULT_CUSTODY_TIER2_PATH,
) -> Tuple[str, str]:
    """Attach self-check reference vectors and save Tier-2 weights JSON (~1-2 KB) to ML & custody."""
    sample_indices: List[int] = []
    for target_regime in ("normal", "benign_slowdown", "anchor_drag"):
        matches = [
            i for i, r in enumerate(records) if r["split"] == "test" and r["regime"] == target_regime
        ]
        sample_indices.extend(matches[:2])
    # Also include a deep-water negative example and a zero-heading edge case
    deep_neg = next(
        (i for i, r in enumerate(records) if r["regime"] != "anchor_drag" and r["cfg"].depth_m > 120.0),
        None,
    )
    if deep_neg is not None and deep_neg not in sample_indices:
        sample_indices.append(deep_neg)

    self_check_vectors: List[Dict[str, Any]] = []
    for idx in sample_indices:
        rec = records[idx]
        feats = [float(rec["tier2_features"][fn]) for fn in TIER2_FEATURE_NAMES]
        prob = float(score_tier2_numpy(np.asarray([feats], dtype=np.float64), tier2_model)[0])
        self_check_vectors.append(
            {
                "regime": rec["regime"],
                "hull_class": rec["cfg"].hull_class,
                "features": [round(v, 6) for v in feats],
                "expected_prob": float(
                    score_tier2_numpy(
                        np.asarray([[round(v, 6) for v in feats]], dtype=np.float64),
                        tier2_model,
                    )[0]
                ),
                "expected_band": tier2_band(
                    float(
                        score_tier2_numpy(
                            np.asarray([[round(v, 6) for v in feats]], dtype=np.float64),
                            tier2_model,
                        )[0]
                    ),
                    tier2_model["thresholds"],
                ),
            }
        )

    payload = {
        "model_name": tier2_model["model_name"],
        "provenance": tier2_model["provenance"],
        "feature_names": tier2_model["feature_names"],
        "scaler": {
            "mean": [round(v, 8) for v in tier2_model["scaler"]["mean"]],
            "std": [round(v, 8) for v in tier2_model["scaler"]["std"]],
        },
        "weights": [round(v, 8) for v in tier2_model["weights"]],
        "bias": round(float(tier2_model["bias"]), 8),
        "thresholds": dict(tier2_model["thresholds"]),
        "self_check_vectors": self_check_vectors,
    }
    # Recompute expected_prob using the exact rounded JSON weights/scaler for <1e-12 parity
    for vec in payload["self_check_vectors"]:
        p_exact = float(
            score_tier2_numpy(np.asarray([vec["features"]], dtype=np.float64), payload)[0]
        )
        vec["expected_prob"] = p_exact
        vec["expected_band"] = tier2_band(p_exact, payload["thresholds"])

    abs_ml = os.path.abspath(ml_weights_path)
    os.makedirs(os.path.dirname(abs_ml), exist_ok=True)
    with open(abs_ml, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    abs_custody = os.path.abspath(custody_weights_path)
    os.makedirs(os.path.dirname(abs_custody), exist_ok=True)
    shutil.copy2(abs_ml, abs_custody)
    return (abs_ml, abs_custody)


def compute_sustained_unilateral_crab(
    track: Sequence[Dict[str, Any]],
    window_s: float = 240.0,
    min_sog_kn: float = 2.5,
    after_min: float = 10.0,
) -> Tuple[float, Optional[float]]:
    """Compute peak sustained unilateral crab angle `|median(HDG - COG)| * consistency` on `track`.

    Args:
        track: Ordered sequence of AIS fixes.
        window_s: Sliding window duration in seconds for unilateral crab evaluation.
        min_sog_kn: Minimum SOG in knots for valid COG-HDG comparison.
        after_min: Minimum elapsed time in minutes for post-maneuver crab evaluation.

    Returns:
        Tuple `(max_unilateral_crab_deg, first_exceed_4deg_min)` where `first_exceed_4deg_min`
        is the elapsed minutes from `track[0]["ts"]` when unilateral crab first exceeds `4.0 deg`.
    """
    best_crab = 0.0
    first_4deg_min: Optional[float] = None
    t0_ms = float(track[0]["ts"])
    need_ms = window_s * 1000.0

    a = 0
    for b in range(len(track)):
        t_b_min = (float(track[b]["ts"]) - t0_ms) / 60000.0
        if t_b_min < after_min:
            continue
        while a < b and (
            (float(track[b]["ts"]) - float(track[a + 1]["ts"])) >= need_ms
            or (float(track[a]["ts"]) - t0_ms) / 60000.0 < after_min
        ):
            a += 1
        if (float(track[b]["ts"]) - float(track[a]["ts"])) < 170_000.0:
            continue
        seg = track[a : b + 1]
        diffs = [
            _signed_diff_deg(float(f["heading"]), float(f["cog"]))
            for f in seg
            if float(f["sog"]) >= min_sog_kn
        ]
        if len(diffs) < 3:
            continue
        pos = sum(1 for d in diffs if d > 0.0)
        sign_frac = max(pos, len(diffs) - pos) / float(len(diffs))
        unilateral_weight = max(0.0, (sign_frac - 0.5) * 2.0)
        eff_crab = abs(float(statistics.median(diffs))) * (unilateral_weight ** 2)
        if eff_crab > best_crab:
            best_crab = eff_crab
        if first_4deg_min is None and eff_crab >= 4.0 and sign_frac >= 0.85:
            first_4deg_min = t_b_min

    return (best_crab, first_4deg_min)


def compute_slow_corridor_continuous_score(
    track: Sequence[Dict[str, Any]],
    ind01_hits: Sequence[Tuple[str, Dict[str, Any], Dict[str, Any], float]],
    window_s: float = 1800.0,
) -> float:
    """Compute a continuous score for IND-01 so ROC-AUC is well-ordered below and above firing."""
    if ind01_hits:
        return 1.0 + float(ind01_hits[0][3])
    need_ms = window_s * 1000.0
    min_p90 = 30.0
    a = 0
    for b in range(len(track)):
        while a < b and (float(track[b]["ts"]) - float(track[a + 1]["ts"])) >= need_ms:
            a += 1
        if (float(track[b]["ts"]) - float(track[a]["ts"])) < need_ms:
            continue
        sogs = sorted(float(f["sog"]) for f in track[a : b + 1])
        if len(sogs) >= 3:
            idx90 = min(len(sogs) - 1, int(0.90 * (len(sogs) - 1)))
            if sogs[idx90] < min_p90:
                min_p90 = sogs[idx90]
    return max(0.0, min(0.99, (13.5 - min_p90) / 10.0))


def roc_auc_and_curve(
    y_true: Sequence[int],
    y_score: Sequence[float],
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Compute exact trapezoidal ROC-AUC and `(fpr, tpr)` arrays using NumPy."""
    yt = np.asarray(y_true, dtype=np.int32)
    ys = np.asarray(y_score, dtype=np.float64)
    n_pos = int(np.sum(yt == 1))
    n_neg = int(np.sum(yt == 0))
    if n_pos == 0 or n_neg == 0:
        return (0.0, np.array([0.0, 1.0]), np.array([0.0, 1.0]))

    thresholds = np.unique(ys)[::-1]
    fpr_list: List[float] = [0.0]
    tpr_list: List[float] = [0.0]
    for th in thresholds:
        pred_pos = ys >= th
        tp = int(np.sum(pred_pos & (yt == 1)))
        fp = int(np.sum(pred_pos & (yt == 0)))
        fpr_list.append(fp / float(n_neg))
        tpr_list.append(tp / float(n_pos))
    fpr_list.append(1.0)
    tpr_list.append(1.0)

    fpr_arr = np.asarray(fpr_list, dtype=np.float64)
    tpr_arr = np.asarray(tpr_list, dtype=np.float64)
    auc_val = float(np.trapezoid(tpr_arr, fpr_arr))
    return (auc_val, fpr_arr, tpr_arr)


def binary_metrics(
    y_true: Sequence[int],
    y_pred: Sequence[bool],
) -> Tuple[float, float, float]:
    """Compute `(precision, recall, f1)` for binary predictions."""
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and not yp)
    precision = tp / float(tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / float(tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if (precision + recall) > 0.0
        else 0.0
    )
    return (precision, recall, f1)


def evaluate_all_tracks(
    dataset: Sequence[Tuple[EpisodeConfig, List[Dict[str, Any]], Dict[str, np.ndarray]]],
    corridor_idx: custody_geo.SegmentIndex,
    weights_path: str = DEFAULT_WEIGHTS_PATH,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run KAIKU's detectors (`IND-01`, `IND-02`, `IND-08`, `Combined`) + train/evaluate Tier-2 LogReg."""
    model = mlp_infer.load_model(weights_path)
    th = dict(custody_ind.THRESHOLDS)

    records: List[Dict[str, Any]] = []
    for cfg, track, hist in dataset:
        ind01_hits = custody_ind.ind01_slow_on_corridor(track, corridor_idx, th)
        ind02_hits = custody_ind.ind02_cog_hdg_bias(track, th)
        ind08_hits = custody_ind.ind08_motion_anomaly(
            track,
            th,
            corridor_idx=corridor_idx,
            weights_path=weights_path,
            ship_type=cfg.ship_type,
        )

        t_mins, rz_all, rz_braking, hit_indices, step_details = compute_step_mlp_timeline(
            track,
            model,
            return_steps=True,
            corridor_idx=corridor_idx,
            th=th,
            ship_type=cfg.ship_type,
        )
        sustained_crab_deg, first_crab_min = compute_sustained_unilateral_crab(track)
        tier2_feats = extract_tier2_features(cfg, track, step_details, th=th)

        braking_sorted = sorted(rz_braking, reverse=True)
        second_braking_rz = braking_sorted[1] if len(braking_sorted) >= 2 else 0.0
        peak_braking_rz = braking_sorted[0] if braking_sorted else 0.0

        score_ind01 = compute_slow_corridor_continuous_score(track, ind01_hits)
        score_ind02 = sustained_crab_deg / 8.0
        score_ind08 = second_braking_rz
        rz_norm = math.log1p(peak_braking_rz / mlp_infer.RADIAL_Z_95CI)
        crab_excess = max(0.0, sustained_crab_deg - 3.5) / 4.0
        score_combined = rz_norm * crab_excess + 0.05 * (sustained_crab_deg / 4.0)

        fired_ind01 = len(ind01_hits) > 0
        fired_ind02 = len(ind02_hits) > 0
        fired_ind08 = len(ind08_hits) > 0
        fired_combined = fired_ind08 and (sustained_crab_deg >= 4.5 or fired_ind02)

        t0_ms = float(track[0]["ts"])
        t_drop_min = cfg.t_maneuver_s / 60.0

        lead_ind01: Optional[float] = None
        if fired_ind01:
            t_det_min = (float(ind01_hits[0][2]["t_end_ms"]) - t0_ms) / 60000.0
            if t_det_min >= t_drop_min:
                lead_ind01 = t_det_min - t_drop_min

        lead_ind02: Optional[float] = None
        if fired_ind02:
            t_det_min = (float(ind02_hits[0][2]["t_end_ms"]) - t0_ms) / 60000.0
            if t_det_min >= t_drop_min:
                lead_ind02 = t_det_min - t_drop_min

        lead_ind08: Optional[float] = None
        if fired_ind08 and len(hit_indices) >= 2:
            post_drop_hits = [
                idx
                for idx in hit_indices
                if (float(track[idx]["ts"]) - t0_ms) / 60000.0 >= t_drop_min
            ]
            if len(post_drop_hits) >= 2:
                t_det_min = (float(track[post_drop_hits[1]]["ts"]) - t0_ms) / 60000.0
                lead_ind08 = t_det_min - t_drop_min

        lead_combined: Optional[float] = None
        if fired_combined and lead_ind08 is not None and first_crab_min is not None:
            lead_combined = max(lead_ind08, first_crab_min - t_drop_min)

        records.append(
            {
                "cfg": cfg,
                "track": track,
                "hist": hist,
                "regime": cfg.regime,
                "hull_class": cfg.hull_class,
                "t_step_min": t_mins,
                "rz_all": rz_all,
                "rz_braking": rz_braking,
                "peak_braking_rz": peak_braking_rz,
                "sustained_crab_deg": sustained_crab_deg,
                "tier2_features": tier2_feats,
                "score_IND-01": score_ind01,
                "score_IND-02": score_ind02,
                "score_IND-08": score_ind08,
                "score_Combined": score_combined,
                "fired_IND-01": fired_ind01,
                "fired_IND-02": fired_ind02,
                "fired_IND-08": fired_ind08,
                "fired_Combined": fired_combined,
                "lead_IND-01": lead_ind01,
                "lead_IND-02": lead_ind02,
                "lead_IND-08": lead_ind08,
                "lead_Combined": lead_combined,
            }
        )

    # Strict 70% train / 30% test split stratified by (regime, hull_class)
    train_idx, test_idx = stratified_train_test_split(records, test_frac=0.30, seed=seed)
    X_all = np.asarray(
        [[r["tier2_features"][fn] for fn in TIER2_FEATURE_NAMES] for r in records],
        dtype=np.float64,
    )
    y_all = np.asarray([1 if r["regime"] == "anchor_drag" else 0 for r in records], dtype=np.float64)

    tier2_model = train_tier2_logreg(X_all[train_idx], y_all[train_idx], l2_reg=1.0)
    probs_all = score_tier2_numpy(X_all, tier2_model)

    train_set = set(train_idx)
    for idx, rec in enumerate(records):
        prob = float(probs_all[idx])
        rec["split"] = "train" if idx in train_set else "test"
        rec["score_Tier2"] = prob
        rec["fired_Tier2"] = prob >= 0.50
        rec["fired_Tier2_mod"] = prob >= TIER2_THRESHOLDS["moderate"]
        rec["fired_Tier2_high"] = prob >= TIER2_THRESHOLDS["high"]
        rec["tier2_band"] = tier2_band(prob, tier2_model["thresholds"])
        # Tier-2 acts immediately at the peak IND-08 braking window
        rec["lead_Tier2"] = rec["lead_IND-08"] if (rec["fired_IND-08"] and rec["fired_Tier2"]) else None

    detectors = ("IND-01", "IND-02", "IND-08", "Combined", "Tier2")
    tasks = (
        ("anchor_drag_vs_normal", "normal"),
        ("anchor_drag_vs_benign_slowdown", "benign_slowdown"),
        ("anchor_drag_vs_all_negatives", None),
    )

    test_records = [records[i] for i in test_idx]
    benchmarks: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for split_key, split_pool in (("all", records), ("test", test_records)):
        benchmarks[split_key] = {}
        for task_name, neg_regime in tasks:
            if neg_regime is None:
                sub = split_pool
            else:
                sub = [r for r in split_pool if r["regime"] in ("anchor_drag", neg_regime)]
            y_true = [1 if r["regime"] == "anchor_drag" else 0 for r in sub]
            benchmarks[split_key][task_name] = {}
            for det in detectors:
                y_score = [float(r[f"score_{det}"]) for r in sub]
                y_pred = [bool(r[f"fired_{det}"]) for r in sub]
                auc_val, fpr_arr, tpr_arr = roc_auc_and_curve(y_true, y_score)
                prec, rec_v, f1 = binary_metrics(y_true, y_pred)
                benchmarks[split_key][task_name][det] = {
                    "roc_auc": auc_val,
                    "precision": prec,
                    "recall": rec_v,
                    "f1": f1,
                    "fpr": fpr_arr,
                    "tpr": tpr_arr,
                }

    # Backwards-compatible top-level task keys (using held-out 30% test set for honest reporting)
    benchmarks["anchor_drag_vs_normal"] = benchmarks["test"]["anchor_drag_vs_normal"]
    benchmarks["anchor_drag_vs_benign_slowdown"] = benchmarks["test"]["anchor_drag_vs_benign_slowdown"]
    benchmarks["anchor_drag_vs_all_negatives"] = benchmarks["test"]["anchor_drag_vs_all_negatives"]

    drag_records = [r for r in records if r["regime"] == "anchor_drag"]
    lead_times: Dict[str, Dict[str, float]] = {}
    for det in detectors:
        vals = [
            float(r[f"lead_{det}"])
            for r in drag_records
            if r[f"lead_{det}"] is not None
        ]
        lead_times[det] = {
            "mean_min": float(np.mean(vals)) if vals else float("nan"),
            "median_min": float(np.median(vals)) if vals else float("nan"),
            "std_min": float(np.std(vals)) if vals else float("nan"),
            "detected_count": float(len(vals)),
        }

    return {
        "records": records,
        "train_idx": train_idx,
        "test_idx": test_idx,
        "tier2_model": tier2_model,
        "benchmarks": benchmarks,
        "lead_times": lead_times,
    }


def save_validation_plot(
    eval_results: Dict[str, Any],
    output_path: str = DEFAULT_PLOT_PATH,
) -> str:
    """Render and save a 2-panel validation figure (`Panel A`: timelines; `Panel B`: Test ROC + Lead-Time)."""
    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)

    records: List[Dict[str, Any]] = eval_results["records"]
    benign_rec = next(
        r
        for r in records
        if r["regime"] == "benign_slowdown"
        and r["cfg"].hull_class == "aframax_tanker"
        and r["cfg"].slowdown_ramp_s >= 280.0
        and abs(r["cfg"].t_maneuver_s - 540.0) < 90.0
    )
    drag_rec = next(
        r
        for r in records
        if r["regime"] == "anchor_drag"
        and r["cfg"].hull_class == "aframax_tanker"
        and r["cfg"].hawsepipe_side == 1
        and r["cfg"].eta_soil >= 5.5
    )

    fig = plt.figure(figsize=(16.0, 8.6), dpi=160)
    gs = fig.add_gridspec(
        3,
        2,
        width_ratios=[1.14, 1.0],
        height_ratios=[1.0, 1.0, 1.0],
        hspace=0.34,
        wspace=0.31,
    )

    ax_sog = fig.add_subplot(gs[0, 0])
    ax_crab = fig.add_subplot(gs[1, 0], sharex=ax_sog)
    ax_rz = fig.add_subplot(gs[2, 0], sharex=ax_sog)

    t_b = benign_rec["hist"]["t_min"]
    t_d = drag_rec["hist"]["t_min"]

    ax_sog.plot(
        t_b,
        benign_rec["hist"]["sog_kn"],
        color="#2b6cb0",
        lw=2.0,
        label="Benign Engine Slowdown (symmetric thrust reduction)",
    )
    ax_sog.plot(
        t_d,
        drag_rec["hist"]["sog_kn"],
        color="#c53030",
        lw=2.1,
        label="Under-Power Anchor Drag (Fossen + Catenary + Stick-Slip)",
    )
    ax_sog.axvline(10.0, color="#4a5568", ls="--", lw=1.2, label="Anchor Drop (t = 10 min)")
    ax_sog.axhspan(1.0, 5.0, color="#ecc94b", alpha=0.16, label="IND-01 Slow Band (1-5 kn)")
    ax_sog.set_ylabel("SOG (kn)", fontweight="bold")
    ax_sog.set_title(
        "Panel A: 3-DOF Fossen Timelines — Benign Slowdown vs. Anchor Drag",
        fontweight="bold",
        fontsize=10.5,
    )
    ax_sog.grid(True, alpha=0.28)
    ax_sog.legend(loc="upper right", fontsize=8.2, framealpha=0.92)

    ax_crab.plot(
        t_b,
        np.abs(benign_rec["hist"]["crab_deg"]),
        color="#2b6cb0",
        lw=2.0,
        label="Benign Slowdown |HDG - COG| (wind drift)",
    )
    ax_crab.plot(
        t_d,
        np.abs(drag_rec["hist"]["crab_deg"]),
        color="#c53030",
        lw=2.1,
        label="Anchor Drag |HDG - COG| (hawsepipe yaw + counter-rudder)",
    )
    ax_crab.axhline(
        8.0, color="#dd6b20", ls=":", lw=1.4, label="IND-02 Unilateral Threshold (8.0°)"
    )
    ax_crab.axvline(10.0, color="#4a5568", ls="--", lw=1.2)
    ax_crab.set_ylabel("|HDG - COG| (°)", fontweight="bold")
    ax_crab.grid(True, alpha=0.28)
    ax_crab.legend(loc="upper left", fontsize=8.2, framealpha=0.92)

    ax_rz.plot(
        benign_rec["t_step_min"],
        benign_rec["rz_all"],
        color="#2b6cb0",
        marker="o",
        ms=3.5,
        lw=1.6,
        label="Benign Slowdown IND-08 Radial Z",
    )
    ax_rz.plot(
        drag_rec["t_step_min"],
        drag_rec["rz_all"],
        color="#c53030",
        marker="s",
        ms=3.8,
        lw=1.8,
        label="Anchor Drag IND-08 Radial Z (ShipMotionGaussianMLP v3)",
    )
    ax_rz.axhline(
        mlp_infer.RADIAL_Z_95CI,
        color="#2f855a",
        ls="--",
        lw=1.4,
        label=f"95% CI Threshold (z = {mlp_infer.RADIAL_Z_95CI:.2f})",
    )
    ax_rz.axvline(10.0, color="#4a5568", ls="--", lw=1.2)
    ax_rz.set_xlabel("Episode Elapsed Time (minutes)", fontweight="bold")
    ax_rz.set_ylabel("IND-08 Radial Z", fontweight="bold")
    ax_rz.grid(True, alpha=0.28)
    ax_rz.legend(loc="upper right", fontsize=8.2, framealpha=0.92)

    gs_right = gs[:, 1].subgridspec(2, 1, height_ratios=[1.15, 0.95], hspace=0.35)
    ax_roc = fig.add_subplot(gs_right[0, 0])
    ax_lead = fig.add_subplot(gs_right[1, 0])

    bm_hard = eval_results["benchmarks"]["test"]["anchor_drag_vs_benign_slowdown"]
    palette = {
        "Tier2": ("#805ad5", "-", 2.6, "Tier-2 LogReg (5 AIS+Depth Features)"),
        "Combined": ("#c53030", "--", 2.1, "Combined (IND-08 + Unilateral Crab)"),
        "IND-08": ("#2b6cb0", "--", 1.9, "IND-08 (ShipMotionGaussianMLP v3)"),
        "IND-02": ("#dd6b20", "-.", 1.8, "IND-02 (20-min COG-HDG Bias Rule)"),
        "IND-01": ("#718096", ":", 1.8, "IND-01 (30-min Corridor Slow Rule)"),
    }
    for det_key in ("Tier2", "Combined", "IND-08", "IND-02", "IND-01"):
        color, ls, lw, lbl = palette[det_key]
        m = bm_hard[det_key]
        ax_roc.plot(
            m["fpr"],
            m["tpr"],
            color=color,
            ls=ls,
            lw=lw,
            label=f"{lbl} (AUC = {m['roc_auc']:.3f}, F1 = {m['f1']:.3f})",
        )
    ax_roc.plot([0.0, 1.0], [0.0, 1.0], color="#cbd5e0", lw=1.0, ls="--")
    ax_roc.set_xlim(-0.02, 1.02)
    ax_roc.set_ylim(-0.02, 1.03)
    ax_roc.set_xlabel("False Positive Rate (Benign Slowdown, 30% Held-Out Test)", fontweight="bold")
    ax_roc.set_ylabel("True Positive Rate (Anchor Drag)", fontweight="bold")
    ax_roc.set_title(
        "Panel B1: Held-Out Test ROC — Anchor Drag vs. Benign Slowdown (3 Hulls)",
        fontweight="bold",
        fontsize=10.5,
    )
    ax_roc.grid(True, alpha=0.28)
    ax_roc.legend(loc="lower right", fontsize=7.8, framealpha=0.94)

    lt = eval_results["lead_times"]
    bar_keys = ["IND-08", "Tier2", "Combined", "IND-02", "IND-01"]
    bar_labels = [
        "IND-08\n(ML v3)",
        "Tier-2\n(AIS+Depth)",
        "Combined\n(IND-08+Crab)",
        "IND-02\n(20-min Bias)",
        "IND-01\n(30-min Slow)",
    ]
    means = [lt[k]["mean_min"] for k in bar_keys]
    stds = [lt[k]["std_min"] for k in bar_keys]
    colors = ["#2b6cb0", "#805ad5", "#c53030", "#dd6b20", "#718096"]

    bars = ax_lead.barh(
        bar_labels[::-1],
        means[::-1],
        xerr=stds[::-1],
        color=colors[::-1],
        alpha=0.88,
        height=0.55,
        capsize=4,
    )
    for bar, val, err in zip(bars, means[::-1], stds[::-1]):
        if math.isfinite(val):
            ax_lead.text(
                val + err + 0.75,
                bar.get_y() + bar.get_height() / 2.0,
                f"{val:.2f} min (±{err:.2f})",
                va="center",
                ha="left",
                fontsize=8.5,
                fontweight="bold",
            )
    finite_max = max((m + s for m, s in zip(means, stds) if math.isfinite(m)), default=25.0)
    ax_lead.set_xlim(0.0, finite_max + 9.0)
    ax_lead.set_xlabel("Mean Detection Lead-Time After Anchor Drop (minutes)", fontweight="bold")
    ax_lead.set_title(
        "Panel B2: Mean Causal Detection Lead-Time After t_drop = 10 min",
        fontweight="bold",
        fontsize=10.5,
    )
    ax_lead.grid(True, axis="x", alpha=0.28)

    fig.suptitle(
        f"KAIKU Multi-Hull Anchor-Drag Validation ({len(records)} Simulated Episodes · Aframax / Mariner / Feeder)",
        fontsize=12.5,
        fontweight="bold",
        y=0.985,
    )
    fig.savefig(abs_out, bbox_inches="tight")
    plt.close(fig)
    return abs_out


def print_benchmark_report(eval_results: Dict[str, Any], plot_path: str) -> None:
    """Print held-out 30% test metrics and lead-time tables for all detectors and Tier-2."""
    bm_test = eval_results["benchmarks"]["test"]
    lt = eval_results["lead_times"]
    n_total = len(eval_results["records"])
    n_train = len(eval_results["train_idx"])
    n_test = len(eval_results["test_idx"])

    print("=" * 98)
    print(
        f"KAIKU 3-DOF MULTI-HULL ANCHOR-DRAG BENCHMARK ({n_total} EPISODES: {n_train} TRAIN / {n_test} HELD-OUT TEST)"
    )
    print("=" * 98)

    label_map = {
        "IND-01": "IND-01 (30-min Slow Rule)",
        "IND-02": "IND-02 (20-min COG-HDG Bias)",
        "IND-08": "IND-08 (ShipMotionGaussianMLP v3)",
        "Combined": "Combined (IND-08 + Unilateral Crab)",
        "Tier2": "Tier-2 (L2 LogReg, 5 AIS+Depth)",
    }

    for title, key in (
        ("(a) Held-Out 30% Test — Anchor Drag vs. Benign Engine Slowdown", "anchor_drag_vs_benign_slowdown"),
        ("(b) Held-Out 30% Test — Anchor Drag vs. Normal Transit", "anchor_drag_vs_normal"),
        ("(c) Held-Out 30% Test — Overall (Anchor Drag vs. Normal + Benign Slowdown)", "anchor_drag_vs_all_negatives"),
    ):
        print(f"\n{title}")
        print("-" * 98)
        print(
            f"{'Detector':<36} | {'ROC-AUC':>9} | {'Precision':>9} | {'Recall':>9} | {'F1-Score':>9}"
        )
        print("-" * 98)
        for det in ("IND-01", "IND-02", "IND-08", "Combined", "Tier2"):
            m = bm_test[key][det]
            print(
                f"{label_map[det]:<36} | {m['roc_auc']:>9.4f} | {m['precision']:>9.4f} | "
                f"{m['recall']:>9.4f} | {m['f1']:>9.4f}"
            )
        print("-" * 98)

    # Print Tier-2 coefficients
    t2 = eval_results["tier2_model"]
    print("\nTier-2 L2-Regularized Logistic Regression Weights (standardized features):")
    for fn, w, m, s in zip(
        t2["feature_names"], t2["weights"], t2["scaler"]["mean"], t2["scaler"]["std"]
    ):
        print(f"  {fn:<24}: w = {w:+8.4f}  (mean = {m:7.3f}, std = {s:7.3f})")
    print(f"  {'bias':<24}: b = {t2['bias']:+8.4f}")

    print("\nMean Causal Detection Lead-Time After Anchor Drop (t_drop = 10.0 min)")
    print("-" * 98)
    print(
        f"{'Detector':<36} | {'Mean Lead-Time':>16} | {'Median':>12} | {'Std Dev':>10} | {'Gain vs IND-01':>14}"
    )
    print("-" * 98)
    ind01_mean = lt["IND-01"]["mean_min"]
    for det in ("IND-08", "Tier2", "Combined", "IND-02", "IND-01"):
        d = lt[det]
        gain = ind01_mean - d["mean_min"]
        gain_str = f"{gain:+.2f} min" if (math.isfinite(gain) and gain > 0) else "baseline"
        print(
            f"{label_map[det]:<36} | {d['mean_min']:>12.2f} min | {d['median_min']:>8.2f} min | "
            f"{d['std_min']:>6.2f} min | {gain_str:>14}"
        )
    print("-" * 98)
    print(f"Saved validation figure to: {plot_path}")
    print("=" * 98)


def run_self_check(
    eval_results: Optional[Dict[str, Any]] = None,
    params: Optional[VesselHullParams] = None,
    corridor_idx: Optional[custody_geo.SegmentIndex] = None,
    anchor_weights_path: str = DEFAULT_CUSTODY_TIER2_PATH,
) -> int:
    """Run deterministic physics and detector verification assertions across all 3 hulls (`--self-check`)."""
    params = params or HULL_PROFILES["aframax_tanker"]
    rng = np.random.default_rng(12345)

    # 1. Verify deep water (h >= L_c) produces exact 0.0 seabed drag force
    for h_deep, shackles_paid in ((85.0, 3.0), (125.0, 4.0), (165.0, 6.0), (250.0, 8.0)):
        l_c = shackles_paid * SHACKLE_M
        assert h_deep >= l_c, "Test setup requires h >= L_c"
        t_h, fx, fy, n_mom = catenary_seabed_drag(
            depth_m=h_deep,
            chain_length_m=l_c,
            w_chain_nm=params.submerged_chain_w_nm,
            anchor_weight_t=14.0,
            eta_soil=6.5,
            stick_slip_xi=0.2,
            hawsepipe_side=1,
        )
        assert (t_h, fx, fy, n_mom) == (0.0, 0.0, 0.0, 0.0), (
            f"Deep water h={h_deep}m >= L_c={l_c}m must yield zero seabed drag, got {(t_h, fx, fy, n_mom)}"
        )

    # 2. Verify benign engine slowdown has small crab angle (< 3 deg in calm wind)
    cfg_calm_benign = EpisodeConfig(
        mmsi=276999001,
        regime="benign_slowdown",
        lat0_deg=59.85,
        lon0_deg=25.50,
        heading_ref_deg=78.0,
        u_cruise_kn=12.0,
        u_target_slow_kn=6.0,
        t_maneuver_s=600.0,
        slowdown_ramp_s=360.0,
        wind_speed_kn=6.0,
        wind_from_deg=165.0,
        current_speed_kn=0.0,
        current_to_deg=78.0,
        depth_m=50.0,
        chain_shackles=0.0,
        anchor_weight_t=14.0,
        eta_soil=5.0,
        hawsepipe_side=1,
    )
    _, hist_benign = simulate_episode(cfg_calm_benign, params, rng)
    max_benign_crab = float(np.max(np.abs(hist_benign["crab_deg"])))
    assert max_benign_crab < 3.0, (
        f"Benign slowdown in calm wind must have |HDG - COG| < 3.0 deg, got {max_benign_crab:.2f} deg"
    )

    # 3. Verify all 3 hull classes produce physical anchor drag (sustained unilateral crab > 4 deg & braking)
    for hull_name, h_params in HULL_PROFILES.items():
        cfg_drag_test = EpisodeConfig(
            mmsi=276999010,
            regime="anchor_drag",
            lat0_deg=59.85,
            lon0_deg=25.50,
            heading_ref_deg=78.0,
            u_cruise_kn=11.5,
            u_target_slow_kn=4.0,
            t_maneuver_s=600.0,
            slowdown_ramp_s=100.0,
            wind_speed_kn=10.0,
            wind_from_deg=160.0,
            current_speed_kn=0.2,
            current_to_deg=78.0,
            depth_m=45.0,
            chain_shackles=9.0,
            anchor_weight_t=0.5 * (h_params.anchor_weight_min_t + h_params.anchor_weight_max_t),
            eta_soil=6.0,
            hawsepipe_side=1,
            hull_class=hull_name,
            ship_type=h_params.ship_type,
        )
        _, hist_drag = simulate_episode(cfg_drag_test, h_params, rng)
        post_mask = hist_drag["t_min"] >= 15.0
        post_crabs = hist_drag["crab_deg"][post_mask]
        median_abs_crab = float(np.median(np.abs(post_crabs)))
        sign_consistency = float(
            np.mean(post_crabs < 0.0 if np.median(post_crabs) < 0 else post_crabs > 0.0)
        )
        pre_sog = float(np.mean(hist_drag["sog_kn"][hist_drag["t_min"] < 9.5]))
        post_sog = float(np.mean(hist_drag["sog_kn"][post_mask]))
        assert median_abs_crab > 4.0 and sign_consistency >= 0.95, (
            f"{hull_name}: anchor drag must produce sustained unilateral crab > 4 deg, "
            f"got {median_abs_crab:.2f} deg (sign_consistency={sign_consistency:.3f})"
        )
        assert (pre_sog - post_sog) > 5.0, (
            f"{hull_name}: anchor drag must produce substantial speed drop, got {pre_sog:.2f} -> {post_sog:.2f} kn"
        )

    # 4. Verify Tier-2 held-out test ROC-AUC > 0.90 on both anchor_drag vs benign_slowdown and overall
    if corridor_idx is None:
        corridor_idx = build_corridor_index()
    if eval_results is None:
        dataset, _ = generate_dataset(n_per_class=500, seed=42)
        eval_results = evaluate_all_tracks(dataset, corridor_idx)

    auc_t2_benign = float(
        eval_results["benchmarks"]["test"]["anchor_drag_vs_benign_slowdown"]["Tier2"]["roc_auc"]
    )
    auc_t2_overall = float(
        eval_results["benchmarks"]["test"]["anchor_drag_vs_all_negatives"]["Tier2"]["roc_auc"]
    )
    assert auc_t2_benign > 0.90, (
        f"Tier-2 held-out test ROC-AUC vs benign_slowdown must exceed 0.90, got {auc_t2_benign:.4f}"
    )
    assert auc_t2_overall > 0.90, (
        f"Tier-2 held-out test overall ROC-AUC must exceed 0.90, got {auc_t2_overall:.4f}"
    )

    # 5. Verify 0 probability/band mismatches between sim_anchor_drag feature extraction & runtime ind08_motion_anomaly()
    class _ConstDepthGrid:
        def __init__(self, depth_m: float) -> None:
            self._d = float(depth_m)

        def sample(self, lon: float, lat: float) -> float:
            return self._d

    t2_json = custody_motion.load_anchor_tier2_safe(anchor_weights_path, refresh=True)
    assert t2_json is not None, f"Failed to load Tier-2 weights JSON from {anchor_weights_path}"
    th = dict(custody_ind.THRESHOLDS)
    firing_records = [r for r in eval_results["records"] if r["fired_IND-08"]]
    assert firing_records, "Expected at least 1 IND-08-firing episode in dataset"
    mismatches = 0
    for rec in firing_records:
        cfg_r: EpisodeConfig = rec["cfg"]
        hits_rt = custody_ind.ind08_motion_anomaly(
            rec["track"],
            th,
            corridor_idx=corridor_idx,
            weights_path=DEFAULT_WEIGHTS_PATH,
            ship_type=cfg_r.ship_type,
            depth_grid=_ConstDepthGrid(cfg_r.depth_m),
            anchor_weights_path=anchor_weights_path,
        )
        assert len(hits_rt) == 1, (
            f"Expected 1 runtime IND-08 hit for mmsi={cfg_r.mmsi}, got {len(hits_rt)}"
        )
        ev_rt = hits_rt[0][2]
        sim_prob, sim_band = custody_motion.score_anchor_drag(rec["tier2_features"], t2_json)
        if (
            abs(float(ev_rt["anchor_drag_prob"]) - round(sim_prob, 3)) > 1e-9
            or ev_rt["anchor_drag_band"] != sim_band
            or rec["tier2_band"] != ev_rt["anchor_drag_band"]
        ):
            mismatches += 1
    assert mismatches == 0, (
        f"Found {mismatches} probability/band mismatches across {len(firing_records)} IND-08-firing episodes"
    )

    print(
        "[sim_anchor_drag] SELF-CHECK PASSED:\n"
        f"  1. Deep water (h >= L_c) seabed force:         0.0 N (exact)\n"
        f"  2. Calm benign slowdown max |HDG - COG|:       {max_benign_crab:.2f}° (< 3.0°)\n"
        f"  3. All 3 hull profiles (Aframax/Mariner/Feeder) drag crab > 4° & ΔSOG > 5 kn\n"
        f"  4. Tier-2 test ROC-AUC vs benign_slowdown:     {auc_t2_benign:.4f} (> 0.90)\n"
        f"  5. Tier-2 test ROC-AUC overall:                {auc_t2_overall:.4f} (> 0.90)\n"
        f"  6. Runtime IND-08 Tier-2 parity mismatches:    {mismatches} / {len(firing_records)} firing episodes"
    )
    return 0


def main() -> int:
    """Entry point for running the 1,500-episode multi-hull sim, Tier-2 training, export & `--self-check`."""
    parser = argparse.ArgumentParser(
        description="3-DOF Fossen Multi-Hull + Catenary Anchor-Drag Simulator & Tier-2 Trainer."
    )
    parser.add_argument(
        "--n-per-class",
        type=int,
        default=500,
        help="Number of simulated 45-min tracks per class (default: 500 -> 1,500 total)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible simulation (default: 42)",
    )
    parser.add_argument(
        "--plot-out",
        default=DEFAULT_PLOT_PATH,
        help="Output path for the 2-panel validation PNG chart",
    )
    parser.add_argument(
        "--csv-out",
        default=DEFAULT_DATASET_PATH,
        help="Output path for tabular episode-feature CSV dataset",
    )
    parser.add_argument(
        "--tier2-out",
        default=DEFAULT_TIER2_WEIGHTS_PATH,
        help="Output path for Tier-2 weights JSON",
    )
    parser.add_argument(
        "--custody-tier2-out",
        default=DEFAULT_CUSTODY_TIER2_PATH,
        help="Copy destination path in custody_mvp/custody/weights/",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run physics & Tier-2 self-check assertions along with benchmark evaluation",
    )
    args = parser.parse_args()

    t0 = time.perf_counter()
    dataset, params = generate_dataset(n_per_class=args.n_per_class, seed=args.seed)
    corridor_idx = build_corridor_index()
    eval_results = evaluate_all_tracks(dataset, corridor_idx, seed=args.seed)
    csv_path = export_dataset_csv(eval_results["records"], output_path=args.csv_out)
    ml_w_path, custody_w_path = export_tier2_weights(
        eval_results["tier2_model"],
        eval_results["records"],
        ml_weights_path=args.tier2_out,
        custody_weights_path=args.custody_tier2_out,
    )
    plot_path = save_validation_plot(eval_results, output_path=args.plot_out)
    elapsed_s = time.perf_counter() - t0

    print_benchmark_report(eval_results, plot_path=plot_path)
    print(f"Exported dataset CSV ({len(eval_results['records'])} rows) to: {csv_path}")
    print(f"Exported Tier-2 weights JSON ({os.path.getsize(ml_w_path)} B) to: {ml_w_path}")
    print(f"Copied Tier-2 weights JSON to: {custody_w_path}")
    print(f"[sim_anchor_drag] Completed {3 * args.n_per_class} tracks in {elapsed_s:.2f} s.")

    if args.self_check:
        return run_self_check(
            eval_results=eval_results,
            params=params,
            corridor_idx=corridor_idx,
            anchor_weights_path=custody_w_path,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
