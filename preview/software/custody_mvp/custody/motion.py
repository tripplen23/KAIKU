#!/usr/bin/env python3
"""Pure-Python inference module for KAIKU's probabilistic ship-motion Gaussian MLP (IND-08).

Uses only the Python standard library (zero external dependencies) and degrades
gracefully via `load_model_safe()` when weights are missing or corrupt.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import operator
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

try:
    from . import paths as _paths
except ImportError:
    try:
        from custody import paths as _paths  # type: ignore[no-redef]
    except ImportError:
        _paths = None  # type: ignore[assignment]

LOG = logging.getLogger("custody.motion")

FALLBACK_WEIGHTS_PATH: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "weights", "ship_motion_mlp.json"
)
FALLBACK_ANCHOR_WEIGHTS_PATH: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "weights", "anchor_drag_tier2.json"
)

# 2D rotation-invariant 95% confidence threshold: sqrt(chi2_{2, 0.95}) = sqrt(-2 * ln(0.05))
RADIAL_Z_95CI: float = 2.447746830680816

# Valid training domain bounds (2024 Gulf of Finland open-water AIS transit)
VALID_DT_MIN_S: float = 60.0
VALID_DT_MAX_S: float = 300.0
VALID_SOG_MIN_KN: float = 2.0
VALID_SOG_MAX_KN: float = 30.0

MANEUVER_SHIP_TYPE_LABELS: Tuple[str, ...] = (
    "passenger",
    "hsc",
    "wig",
    "ferry",
    "tug",
    "pilot",
    "sar",
    "port tender",
    "dredging",
    "law enforcement",
    "towing",
    "towing long",
    "towing long/wide",
    "diving",
    "diving ops",
    "military",
    "military ops",
    "anti-pollution",
    "medical",
    "medical transport",
    "spare 1",
    "spare 2",
    "not party to conflict",
    "fishing",
    "sailing",
    "pleasure",
    "pleasure craft",
)

_MODEL_CACHE: Dict[str, Dict[str, Any]] = {}
_ANCHOR_MODEL_CACHE: Dict[str, Dict[str, Any]] = {}
_COMPILED_CACHE: Dict[int, Tuple[Any, ...]] = {}
_WARNED_PATHS: Set[str] = set()
_MUL = operator.mul


def is_maneuver_vessel_type(ship_type: Any) -> float:
    """Map AIS numeric `shipType` code or DMA string `"Ship type"` to binary `is_maneuver_vessel`.

    Returns `1.0` for high-maneuverability vessels:
      - Passenger / Ferry / HSC (`40..49`, `60..69`)
      - Tug / Pilot / SAR / Port / Dredging / Law Enforcement / Military (`31..35`, `50..59`)
      - Fishing / Sailing / Pleasure (`30`, `36`, `37`)
    Returns `0.0` for Cargo (`70..79`), Tanker (`80..89`), Other (`90..99`), or Unknown.
    """
    if ship_type is None or isinstance(ship_type, bool):
        return 0.0
    if isinstance(ship_type, (int, float)):
        fval = float(ship_type)
        if not math.isfinite(fval):
            return 0.0
        code = int(fval)
        return 1.0 if ((30 <= code <= 37) or (40 <= code <= 69)) else 0.0
    s = str(ship_type).strip()
    if not s:
        return 0.0
    try:
        fval = float(s)
        if not math.isfinite(fval):
            return 0.0
        code = int(fval)
        return 1.0 if ((30 <= code <= 37) or (40 <= code <= 69)) else 0.0
    except ValueError:
        pass
    return 1.0 if s.lower() in MANEUVER_SHIP_TYPE_LABELS else 0.0


def _resolve_weights_path(weights_path: Optional[str] = None) -> str:
    """Resolve the model weights path following KAIKU_MLP_WEIGHTS -> paths.weights() -> fallback."""
    if weights_path:
        return os.path.abspath(os.path.expanduser(str(weights_path)))
    env_kaiku = os.environ.get("KAIKU_MLP_WEIGHTS")
    if env_kaiku:
        return os.path.abspath(os.path.expanduser(env_kaiku))
    if _paths is not None:
        return _paths.weights()
    return FALLBACK_WEIGHTS_PATH


def _resolve_anchor_weights_path(weights_path: Optional[str] = None) -> str:
    """Resolve the Tier-2 anchor-drag discriminator weights path."""
    if weights_path:
        return os.path.abspath(os.path.expanduser(str(weights_path)))
    env_t2 = os.environ.get("CUSTODY_PATHS_ANCHOR_WEIGHTS")
    if env_t2:
        return os.path.abspath(os.path.expanduser(env_t2))
    if _paths is not None and hasattr(_paths, "anchor_weights"):
        return _paths.anchor_weights()
    return FALLBACK_ANCHOR_WEIGHTS_PATH


def check_domain(
    dt_s: float,
    sog_kn: float,
    min_dt_s: float = VALID_DT_MIN_S,
    max_dt_s: float = VALID_DT_MAX_S,
    min_sog_kn: float = VALID_SOG_MIN_KN,
    max_sog_kn: float = VALID_SOG_MAX_KN,
) -> bool:
    """Check whether step duration `dt_s` and speed `sog_kn` fall within the valid model domain.

    Args:
        dt_s: Elapsed time between consecutive AIS fixes in seconds.
        sog_kn: Vessel speed over ground in knots.
        min_dt_s: Minimum valid step duration in seconds (default 60.0).
        max_dt_s: Maximum valid step duration in seconds (default 300.0).
        min_sog_kn: Minimum valid speed over ground in knots (default 2.0).
        max_sog_kn: Maximum valid speed over ground in knots (default 30.0).

    Returns:
        True if `(dt_s, sog_kn)` lies inside `[min_dt_s, max_dt_s] x (min_sog_kn, max_sog_kn)`.

    Raises:
        ValueError: If `dt_s` or `sog_kn` is NaN or infinite.
    """
    dt_val = float(dt_s)
    sog_val = float(sog_kn)
    if not (math.isfinite(dt_val) and math.isfinite(sog_val)):
        raise ValueError(f"Non-finite domain input: dt_s={dt_s!r}, sog_kn={sog_kn!r}")
    return (float(min_dt_s) <= dt_val <= float(max_dt_s)) and (
        float(min_sog_kn) < sog_val < float(max_sog_kn)
    )


def load_model(weights_path: Optional[str] = None, refresh: bool = False) -> Dict[str, Any]:
    """Load and cache exported MLP weights and feature scaler parameters from JSON.

    Args:
        weights_path: Optional path to `ship_motion_mlp.json`.
        refresh: If True, bypass the in-memory cache and re-read from disk.

    Returns:
        Parsed model dictionary containing `feature_names`, `scaler`, `layers`,
        `eps`, `softplus_threshold`, and `self_check_vectors`.

    Raises:
        FileNotFoundError: If the resolved weights file does not exist.
        KeyError: If required schema keys are missing from the JSON payload.
        ValueError: If scaler or layer structures are invalid.
    """
    path = _resolve_weights_path(weights_path)
    if not refresh and path in _MODEL_CACHE:
        return _MODEL_CACHE[path]
    if path in _MODEL_CACHE:
        old_data = _MODEL_CACHE.pop(path, None)
        if old_data is not None:
            _COMPILED_CACHE.pop(id(old_data), None)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Model weights file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data: Dict[str, Any] = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    for req_key in ("feature_names", "scaler", "layers"):
        if req_key not in data:
            raise KeyError(f"Missing required key '{req_key}' in {path}")

    feature_names = data.get("feature_names")
    if (
        not isinstance(feature_names, list)
        or len(feature_names) < 8
        or not all(isinstance(fn, str) and fn for fn in feature_names)
    ):
        raise ValueError(
            f"Invalid 'feature_names' in {path}: expected list of >= 8 strings"
        )
    n_features = len(feature_names)

    scaler = data.get("scaler")
    if not isinstance(scaler, dict) or "mean" not in scaler or "std" not in scaler:
        raise ValueError(f"Invalid 'scaler' in {path}: expected dict with 'mean' and 'std'")
    mean = scaler.get("mean")
    std = scaler.get("std")
    if (
        not isinstance(mean, list)
        or not isinstance(std, list)
        or len(mean) != n_features
        or len(std) != n_features
    ):
        raise ValueError(
            f"Invalid scaler mean/std lengths in {path}: expected length {n_features}"
        )
    try:
        mean_f = [float(v) for v in mean]
        std_f = [float(v) for v in std]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Non-numeric scaler values in {path}") from exc
    if not all(math.isfinite(v) for v in mean_f) or not all(
        math.isfinite(v) and v > 0.0 for v in std_f
    ):
        raise ValueError(f"Scaler mean/std must be finite with std > 0 in {path}")

    layers = data.get("layers")
    if not isinstance(layers, list) or len(layers) == 0:
        raise ValueError(f"Invalid 'layers' in {path}: expected non-empty list")
    in_dim = n_features
    for idx, layer in enumerate(layers):
        if not isinstance(layer, dict) or "weight" not in layer or "bias" not in layer:
            raise ValueError(f"Layer {idx} in {path} missing 'weight' or 'bias'")
        w = layer.get("weight")
        b = layer.get("bias")
        if (
            not isinstance(w, list)
            or not isinstance(b, list)
            or len(w) == 0
            or len(w) != len(b)
        ):
            raise ValueError(f"Layer {idx} in {path} has invalid weight/bias dimensions")
        try:
            b_f = [float(v) for v in b]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Layer {idx} bias in {path} contains non-numeric values") from exc
        if not all(math.isfinite(v) for v in b_f):
            raise ValueError(f"Layer {idx} bias in {path} contains non-finite values")
        for r_idx, row in enumerate(w):
            if not isinstance(row, list) or len(row) != in_dim:
                raise ValueError(
                    f"Layer {idx} row {r_idx} in {path} has invalid length, expected {in_dim}"
                )
            try:
                row_f = [float(v) for v in row]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Layer {idx} weight in {path} contains non-numeric values"
                ) from exc
            if not all(math.isfinite(v) for v in row_f):
                raise ValueError(f"Layer {idx} weight in {path} contains non-finite values")
        in_dim = len(b)
    if in_dim < 4:
        raise ValueError(f"Final layer output dim in {path} is {in_dim}, expected >= 4")

    compiled_layers = tuple(
        (
            tuple(tuple(float(v) for v in row) for row in layer["weight"]),
            tuple(float(v) for v in layer["bias"]),
            layer.get("activation", "linear") == "relu",
        )
        for layer in layers
    )
    _COMPILED_CACHE[id(data)] = (
        tuple(feature_names),
        tuple(mean_f),
        tuple(std_f),
        compiled_layers,
        float(data.get("eps", 1e-4)),
        float(data.get("softplus_threshold", 20.0)),
    )

    try:
        dummy_pred = predict([0.0] * n_features, model_data=data)
    except Exception as exc:
        _COMPILED_CACHE.pop(id(data), None)
        raise ValueError(f"Dummy forward pass failed for {path}: {exc}") from exc
    if (
        len(dummy_pred) != 4
        or not all(math.isfinite(v) for v in dummy_pred)
        or dummy_pred[2] <= 0.0
        or dummy_pred[3] <= 0.0
    ):
        _COMPILED_CACHE.pop(id(data), None)
        raise ValueError(f"Dummy forward pass produced invalid output for {path}: {dummy_pred!r}")

    _MODEL_CACHE[path] = data
    return data


def load_model_safe(
    weights_path: Optional[str] = None,
    refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """Load model weights safely, returning `None` and logging a warning once on error.

    Args:
        weights_path: Optional path override to `ship_motion_mlp.json`.
        refresh: If True, bypass the in-memory cache.

    Returns:
        Model dictionary if valid and present, or `None` if missing or corrupt.
    """
    path = _resolve_weights_path(weights_path)
    try:
        return load_model(weights_path=path, refresh=refresh)
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        ZeroDivisionError,
        json.JSONDecodeError,
    ) as exc:
        if path not in _WARNED_PATHS:
            _WARNED_PATHS.add(path)
            LOG.warning("IND-08 motion model unavailable (%s): %s", path, exc)
        return None


def _softplus(x: float, threshold: float = 20.0) -> float:
    """Compute numerically stable softplus matching `torch.nn.functional.softplus`."""
    if x > threshold:
        return x
    if x < -threshold:
        return math.exp(x)
    return math.log1p(math.exp(x))


def _linear_layer(
    x: Sequence[float],
    weight: Sequence[Sequence[float]],
    bias: Sequence[float],
) -> List[float]:
    """Compute an affine transformation `y = W @ x + b` in pure Python."""
    if len(weight) != len(bias):
        raise ValueError(f"Weight/bias length mismatch: {len(weight)} != {len(bias)}")
    nx = len(x)
    out: List[float] = []
    for row_w, b in zip(weight, bias):
        if len(row_w) != nx:
            raise ValueError(f"Weight row length {len(row_w)} != input length {nx}")
        out.append(sum(map(_MUL, x, row_w), float(b)))
    return out


def lookup_flow(
    lat: float,
    lon: float,
    v_east: float,
    v_north: float,
    model_data: Optional[Dict[str, Any]] = None,
    weights_path: Optional[str] = None,
) -> Tuple[float, float, float]:
    """Look up historical shipping-lane flow velocity delta `(flow_dv_east, flow_dv_north, has_flow)`.

    Bins `(lat, lon)` into `lat_step x lon_step` grid cells (`0.02 deg x 0.04 deg`) and
    velocity `(v_east, v_north)` into 8 directional heading octants
    (`octant = int(((bearing_deg + 22.5) % 360.0) // 45.0)`).
    Returns `(0.0, 0.0, 0.0)` gracefully when `flow_field` is absent (v1/v2 models),
    any input is non-finite, or the cell is not present in `flow_field["cells"]`.

    Args:
        lat: Vessel latitude in decimal degrees.
        lon: Vessel longitude in decimal degrees.
        v_east: Current eastward velocity component in knots.
        v_north: Current northward velocity component in knots.
        model_data: Optional pre-loaded model dict from `load_model()`.
        weights_path: Optional path override to `ship_motion_mlp.json` if `model_data` is None.

    Returns:
        3-tuple `(flow_dv_east, flow_dv_north, has_flow)` where `has_flow == 1.0` if
        the cell exists in `flow_field["cells"]`, else `(0.0, 0.0, 0.0)`.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        ve_f = float(v_east)
        vn_f = float(v_north)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)
    if not (
        math.isfinite(lat_f)
        and math.isfinite(lon_f)
        and math.isfinite(ve_f)
        and math.isfinite(vn_f)
    ):
        return (0.0, 0.0, 0.0)

    model = model_data if model_data is not None else load_model_safe(weights_path)
    if not isinstance(model, dict):
        return (0.0, 0.0, 0.0)
    flow_field = model.get("flow_field")
    if not isinstance(flow_field, dict):
        return (0.0, 0.0, 0.0)
    cells = flow_field.get("cells")
    if not isinstance(cells, dict) or not cells:
        return (0.0, 0.0, 0.0)

    try:
        lat_step = float(flow_field.get("lat_step", 0.02))
        lon_step = float(flow_field.get("lon_step", 0.04))
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)
    if not (
        math.isfinite(lat_step)
        and math.isfinite(lon_step)
        and lat_step > 0.0
        and lon_step > 0.0
    ):
        return (0.0, 0.0, 0.0)

    bearing_deg = math.degrees(math.atan2(ve_f, vn_f) % (2.0 * math.pi))
    octant = int(((bearing_deg + 22.5) % 360.0) // 45.0) % 8
    lat_bin = int(math.floor(lat_f / lat_step))
    lon_bin = int(math.floor(lon_f / lon_step))
    key = f"{lat_bin},{lon_bin},{octant}"

    cell = cells.get(key)
    if not isinstance(cell, (list, tuple)) or len(cell) < 2:
        return (0.0, 0.0, 0.0)
    try:
        flow_ve = float(cell[0])
        flow_vn = float(cell[1])
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)
    if not (math.isfinite(flow_ve) and math.isfinite(flow_vn)):
        return (0.0, 0.0, 0.0)

    return (flow_ve - ve_f, flow_vn - vn_f, 1.0)


def _extract_feature_vector(
    features_dict_or_list: Union[Dict[str, Any], Sequence[float]],
    feature_names: Sequence[str],
) -> List[float]:
    """Extract and validate an ordered 1D feature vector of shape `(len(feature_names),)` from a dict or sequence."""
    if isinstance(features_dict_or_list, dict):
        vec: List[float] = []
        for name in feature_names:
            if name not in features_dict_or_list:
                raise KeyError(
                    f"Missing required feature '{name}'. Expected: {list(feature_names)}"
                )
            val = float(features_dict_or_list[name])
            if not math.isfinite(val):
                raise ValueError(f"Non-finite value for feature '{name}': {val!r}")
            vec.append(val)
        return vec

    if len(features_dict_or_list) != len(feature_names):
        raise ValueError(
            f"Expected {len(feature_names)} features ({list(feature_names)}), "
            f"got {len(features_dict_or_list)}"
        )
    vec = []
    for idx, raw_v in enumerate(features_dict_or_list):
        val = float(raw_v)
        if not math.isfinite(val):
            raise ValueError(
                f"Non-finite value for feature '{feature_names[idx]}' at index {idx}: {val!r}"
            )
        vec.append(val)
    return vec


def predict(
    features_dict_or_list: Union[Dict[str, Any], Sequence[float]],
    weights_path: Optional[str] = None,
    model_data: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float, float, float]:
    """Predict Gaussian parameters `(mu_dv_east, mu_dv_north, std_east, std_north)`.

    Args:
        features_dict_or_list: Input features of shape `(len(feature_names),)` as either
            a dict keyed by `feature_names` or an ordered sequence matching `model["feature_names"]`
            (supports 8-feature v1, 11-feature v2, and 14-feature v3:
            `[v_east, v_north, sog, dt, wind_along, wind_cross, current_along, current_cross,
            prev_dv_east, prev_dv_north, is_maneuver_vessel, flow_dv_east, flow_dv_north, has_flow]`).
        weights_path: Optional path override to `ship_motion_mlp.json`.
        model_data: Optional pre-loaded model dict from `load_model()`.

    Returns:
        4-tuple `(mu_dv_east, mu_dv_north, std_east, std_north)` in knots.

    Raises:
        ValueError: If any input feature is NaN or infinite.
    """
    model = model_data if model_data is not None else load_model(weights_path)
    compiled = _COMPILED_CACHE.get(id(model))
    if compiled is not None:
        feature_names, mean, std, compiled_layers, eps, sp_thresh = compiled
        raw_x = _extract_feature_vector(features_dict_or_list, feature_names)
        x = [(xi - m) / s for xi, m, s in zip(raw_x, mean, std)]
        for weight_t, bias_t, is_relu in compiled_layers:
            if is_relu:
                x = [
                    val if (val := sum(map(_MUL, x, row_w), b)) > 0.0 else 0.0
                    for row_w, b in zip(weight_t, bias_t)
                ]
            else:
                x = [sum(map(_MUL, x, row_w), b) for row_w, b in zip(weight_t, bias_t)]
    else:
        feature_names = model["feature_names"]
        raw_x = _extract_feature_vector(features_dict_or_list, feature_names)
        mean = model["scaler"]["mean"]
        std = model["scaler"]["std"]
        x = [(xi - float(m)) / float(s) for xi, m, s in zip(raw_x, mean, std)]
        for layer in model["layers"]:
            x = _linear_layer(x, layer["weight"], layer["bias"])
            if layer.get("activation", "linear") == "relu":
                x = [val if val > 0.0 else 0.0 for val in x]
        eps = float(model.get("eps", 1e-4))
        sp_thresh = float(model.get("softplus_threshold", 20.0))

    mu_dv_east = float(x[0])
    mu_dv_north = float(x[1])
    var_east = _softplus(float(x[2]), threshold=sp_thresh) + eps
    var_north = _softplus(float(x[3]), threshold=sp_thresh) + eps

    return (mu_dv_east, mu_dv_north, math.sqrt(var_east), math.sqrt(var_north))


def anomaly_score(
    actual_dv_east: float,
    actual_dv_north: float,
    pred: Tuple[float, float, float, float],
    z_threshold_95ci: float = RADIAL_Z_95CI,
) -> Tuple[float, float, float, float, bool]:
    """Compute directional Z-scores, radial Z, Gaussian NLL, and 2D 95% CI anomaly flag.

    Args:
        actual_dv_east: Observed eastward velocity change over step `dt` (knots).
        actual_dv_north: Observed northward velocity change over step `dt` (knots).
        pred: Predicted tuple `(mu_dv_east, mu_dv_north, std_east, std_north)`
            returned by `predict()`.
        z_threshold_95ci: Rotation-invariant 2D radial Z critical threshold for the
            95% confidence region (default `sqrt(chi2_{2, 0.95}) = 2.447746830680816`).

    Returns:
        5-tuple `(z_east, z_north, radial_z, nll, is_anomaly_95ci)` where `nll`
        matches `torch.nn.GaussianNLLLoss(full=False, reduction="mean")`.

    Raises:
        ValueError: If any input or predicted parameter is NaN, infinite, or has negative std.
    """
    obs_e = float(actual_dv_east)
    obs_n = float(actual_dv_north)
    mu_dv_east, mu_dv_north, std_east, std_north = (
        float(pred[0]),
        float(pred[1]),
        float(pred[2]),
        float(pred[3]),
    )
    thresh = float(z_threshold_95ci)

    for name, val in (
        ("actual_dv_east", obs_e),
        ("actual_dv_north", obs_n),
        ("mu_dv_east", mu_dv_east),
        ("mu_dv_north", mu_dv_north),
        ("std_east", std_east),
        ("std_north", std_north),
        ("z_threshold_95ci", thresh),
    ):
        if not math.isfinite(val):
            raise ValueError(f"Non-finite input to anomaly_score for '{name}': {val!r}")
    if std_east < 0.0 or std_north < 0.0:
        raise ValueError(
            f"Standard deviations must be non-negative, got std_east={std_east}, std_north={std_north}"
        )

    var_east = max(std_east * std_east, 1e-12)
    var_north = max(std_north * std_north, 1e-12)

    err_east = obs_e - mu_dv_east
    err_north = obs_n - mu_dv_north

    z_east = err_east / math.sqrt(var_east)
    z_north = err_north / math.sqrt(var_north)
    radial_z = math.sqrt(z_east * z_east + z_north * z_north)

    nll_east = 0.5 * (math.log(var_east) + (err_east * err_east) / var_east)
    nll_north = 0.5 * (math.log(var_north) + (err_north * err_north) / var_north)
    nll = 0.5 * (nll_east + nll_north)

    is_anomaly_95ci = bool(radial_z > thresh)
    return (z_east, z_north, radial_z, nll, is_anomaly_95ci)


def load_anchor_tier2_safe(
    weights_path: Optional[str] = None,
    refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """Load and validate Tier-2 physics-informed anchor-drag logistic regression weights safely.

    Degrades gracefully to `None` (logging a warning once per path) when missing or corrupt.
    """
    path = _resolve_anchor_weights_path(weights_path)
    if not refresh and path in _ANCHOR_MODEL_CACHE:
        return _ANCHOR_MODEL_CACHE[path]
    if path in _ANCHOR_MODEL_CACHE:
        _ANCHOR_MODEL_CACHE.pop(path, None)

    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Tier-2 weights file not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object in {path}")
        for req_key in ("feature_names", "scaler", "weights", "bias"):
            if req_key not in data:
                raise KeyError(f"Missing required key '{req_key}' in {path}")

        feature_names = data["feature_names"]
        if (
            not isinstance(feature_names, list)
            or not feature_names
            or not all(isinstance(fn, str) and fn for fn in feature_names)
        ):
            raise ValueError(f"Invalid 'feature_names' in {path}")
        n_features = len(feature_names)

        scaler = data["scaler"]
        if not isinstance(scaler, dict) or "mean" not in scaler or "std" not in scaler:
            raise ValueError(f"Invalid 'scaler' in {path}")
        mean = scaler["mean"]
        std = scaler["std"]
        if (
            not isinstance(mean, list)
            or not isinstance(std, list)
            or len(mean) != n_features
            or len(std) != n_features
        ):
            raise ValueError(f"Invalid scaler lengths in {path}")
        mean_f = [float(v) for v in mean]
        std_f = [float(v) for v in std]
        if not all(math.isfinite(v) for v in mean_f) or not all(
            math.isfinite(v) and v > 0.0 for v in std_f
        ):
            raise ValueError(f"Non-finite scaler or std <= 0 in {path}")

        weights = data["weights"]
        if not isinstance(weights, list) or len(weights) != n_features:
            raise ValueError(f"Invalid 'weights' length in {path}")
        weights_f = [float(v) for v in weights]
        if not all(math.isfinite(v) for v in weights_f):
            raise ValueError(f"Non-finite weights in {path}")

        bias_f = float(data["bias"])
        if not math.isfinite(bias_f):
            raise ValueError(f"Non-finite bias in {path}")

        thresholds = data.get("thresholds")
        if thresholds is not None:
            if not isinstance(thresholds, dict):
                raise ValueError(f"Invalid 'thresholds' in {path}")
            hi = float(thresholds.get("high", 0.70))
            mod = float(thresholds.get("moderate", 0.35))
            if not (math.isfinite(hi) and math.isfinite(mod) and 0.0 <= mod <= hi <= 1.0):
                raise ValueError(f"Invalid threshold bounds in {path}")

        prob_chk, band_chk = score_anchor_drag([0.0] * n_features, data)
        if not math.isfinite(prob_chk) or band_chk not in ("HIGH", "MODERATE", "LOW"):
            raise ValueError(f"Dummy Tier-2 evaluation invalid in {path}")

        _ANCHOR_MODEL_CACHE[path] = data
        return data
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        ZeroDivisionError,
        json.JSONDecodeError,
    ) as exc:
        if path not in _WARNED_PATHS:
            _WARNED_PATHS.add(path)
            LOG.warning("IND-08 Tier-2 anchor-drag model unavailable (%s): %s", path, exc)
        return None


def score_anchor_drag(
    features: Union[Dict[str, Any], Sequence[float]],
    model_data: Dict[str, Any],
) -> Tuple[float, str]:
    """Score Tier-2 anchor-drag probability and risk band purely in Python stdlib.

    Args:
        features: Dict keyed by `model_data["feature_names"]` or ordered sequence of 5 floats:
            `[peak_radial_z_capped, braking_kn, unilateral_crab_deg, crab_sign_consistency, seabed_reachable]`.
        model_data: Loaded model dict from `load_anchor_tier2_safe()`.

    Returns:
        2-tuple `(prob, band)` where `prob` in `[0.0, 1.0]` and `band` in `("HIGH", "MODERATE", "LOW")`.
    """
    if not isinstance(model_data, dict):
        raise ValueError("model_data must be a dictionary")
    feature_names = model_data["feature_names"]
    raw_x = _extract_feature_vector(features, feature_names)
    mean = model_data["scaler"]["mean"]
    std = model_data["scaler"]["std"]
    weights = model_data["weights"]
    bias = float(model_data["bias"])
    if not math.isfinite(bias):
        raise ValueError(f"Non-finite bias: {bias!r}")

    z = bias
    for xi, m, s, w in zip(raw_x, mean, std, weights):
        m_f, s_f, w_f = float(m), float(s), float(w)
        if not (math.isfinite(m_f) and math.isfinite(s_f) and s_f > 0.0 and math.isfinite(w_f)):
            raise ValueError("Non-finite scaler/weight parameter in Tier-2 model")
        z += w_f * ((xi - m_f) / s_f)

    if z >= 0.0:
        prob = 1.0 / (1.0 + math.exp(-min(z, 700.0)))
    else:
        ez = math.exp(max(z, -700.0))
        prob = ez / (1.0 + ez)

    thresholds = model_data.get("thresholds") or {}
    high_th = float(thresholds.get("high", 0.70))
    mod_th = float(thresholds.get("moderate", 0.35))
    if prob >= high_th:
        band = "HIGH"
    elif prob >= mod_th:
        band = "MODERATE"
    else:
        band = "LOW"
    return (prob, band)


def _run_self_check(weights_path: Optional[str] = None) -> int:
    """Verify stdlib-only execution, input guards, and `< 1e-5` numerical parity with PyTorch."""
    forbidden = [m for m in ("torch", "numpy", "pandas", "scipy") if m in sys.modules]
    if forbidden:
        print(f"FAIL: External modules loaded in self-check: {forbidden}", file=sys.stderr)
        return 1

    model = load_model(weights_path)
    feature_names: List[str] = model["feature_names"]
    resolved_path = _resolve_weights_path(weights_path)
    print(f"[custody.motion] Loaded weights from: {resolved_path}")
    print(f"[custody.motion] Python executable:   {sys.executable} ({sys.version.split()[0]})")
    print(f"[custody.motion] Architecture:        {model.get('architecture', '8->64->64->4')}")
    print(f"[custody.motion] Features ({len(feature_names)}):       {feature_names}")

    vectors = model.get("self_check_vectors", [])
    if not vectors:
        print("FAIL: No self_check_vectors found in weights JSON.", file=sys.stderr)
        return 1

    max_diff = 0.0
    for i, vec in enumerate(vectors):
        feats_list: List[float] = vec["features"]
        feats_dict: Dict[str, float] = dict(zip(feature_names, feats_list))
        pred_list = predict(feats_list, model_data=model)
        pred_dict = predict(feats_dict, model_data=model)

        for a, b in zip(pred_list, pred_dict):
            if abs(a - b) > 1e-12:
                print(f"FAIL: Dict vs List mismatch on vector {i}", file=sys.stderr)
                return 1

        ref: List[float] = vec["expected_pred"]
        sample_max = max(abs(p - r) for p, r in zip(pred_list, ref))
        if sample_max > max_diff:
            max_diff = sample_max

        actual_dv: List[float] = vec["actual_dv"]
        _, _, _, nll, _ = anomaly_score(actual_dv[0], actual_dv[1], pred_list)
        if "expected_nll" in vec:
            nll_diff = abs(nll - float(vec["expected_nll"]))
            if nll_diff > max_diff:
                max_diff = nll_diff

    print(f"[custody.motion] Checked {len(vectors)} PyTorch reference vectors | max_abs_diff = {max_diff:.3e}")
    if max_diff >= 1e-5:
        print(f"FAIL: max_abs_diff {max_diff:.3e} >= 1e-5 tolerance", file=sys.stderr)
        return 1

    if load_model_safe("/nonexistent_weights_file_12345.json") is not None:
        print("FAIL: load_model_safe() did not return None on missing file", file=sys.stderr)
        return 1
    if lookup_flow(float("nan"), 25.0, 10.0, 0.0, model) != (0.0, 0.0, 0.0):
        print("FAIL: lookup_flow() did not return (0.0, 0.0, 0.0) on NaN input", file=sys.stderr)
        return 1
    if lookup_flow(0.0, 0.0, 10.0, 0.0, model) != (0.0, 0.0, 0.0):
        print("FAIL: lookup_flow() did not return (0.0, 0.0, 0.0) on OOD coordinates", file=sys.stderr)
        return 1

    # Tier-2 Anchor-Drag Discriminator self-check
    t2_model = load_anchor_tier2_safe()
    if t2_model is None:
        print("FAIL: load_anchor_tier2_safe() returned None for default weights", file=sys.stderr)
        return 1
    t2_vecs = t2_model.get("self_check_vectors", [])
    if not t2_vecs:
        print("FAIL: No self_check_vectors in Tier-2 weights JSON", file=sys.stderr)
        return 1
    t2_names = t2_model["feature_names"]
    t2_max_diff = 0.0
    for i, vec in enumerate(t2_vecs):
        flist = vec["features"]
        fdict = dict(zip(t2_names, flist))
        p_l, b_l = score_anchor_drag(flist, t2_model)
        p_d, b_d = score_anchor_drag(fdict, t2_model)
        if abs(p_l - p_d) > 1e-12 or b_l != b_d:
            print(f"FAIL: Tier-2 dict vs list mismatch on vector {i}", file=sys.stderr)
            return 1
        diff = abs(p_l - float(vec["expected_prob"]))
        if diff > t2_max_diff:
            t2_max_diff = diff
        if b_l != vec["expected_band"]:
            print(f"FAIL: Tier-2 band mismatch on vector {i}: {b_l} != {vec['expected_band']}", file=sys.stderr)
            return 1
    print(f"[custody.motion] Tier-2 checked {len(t2_vecs)} vectors | max_abs_diff = {t2_max_diff:.3e}")
    if t2_max_diff >= 1e-6:
        print(f"FAIL: Tier-2 max_abs_diff {t2_max_diff:.3e} >= 1e-6", file=sys.stderr)
        return 1

    try:
        score_anchor_drag([float("nan")] * len(t2_names), t2_model)
        print("FAIL: score_anchor_drag() did not reject NaN input", file=sys.stderr)
        return 1
    except ValueError:
        pass

    if load_anchor_tier2_safe("/nonexistent_anchor_tier2_12345.json") is not None:
        print("FAIL: load_anchor_tier2_safe() did not degrade gracefully on missing file", file=sys.stderr)
        return 1

    print("[custody.motion] SELF-CHECK PASSED (zero external dependencies, < 1e-5 MLP & < 1e-6 Tier-2 parity).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KAIKU pure-Python ship-motion MLP inference.")
    parser.add_argument("--weights", default=None, help="Path to ship_motion_mlp.json")
    parser.add_argument("--self-check", action="store_true", help="Run parity & anomaly self-check")
    args = parser.parse_args()
    if args.self_check:
        sys.exit(_run_self_check(args.weights))
    parser.print_help()
