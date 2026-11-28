#!/usr/bin/env python3
"""Pure-Python inference module for KAIKU's probabilistic ship-motion Gaussian MLP.

Uses only the Python standard library (zero external dependencies) so it can run
under any system Python 3.9+ interpreter and drop directly into
`KAIKU/preview/software/custody_mvp/custody/`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

DEFAULT_WEIGHTS_PATH: str = os.environ.get(
    "KAIKU_MLP_WEIGHTS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights", "ship_motion_mlp.json"),
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


def is_maneuver_vessel_type(ship_type: Any) -> float:
    """Map AIS numeric `shipType` code or DMA string `"Ship type"` to binary `is_maneuver_vessel`.

    Returns `1.0` for high-maneuverability vessels:
      - Passenger / Ferry / HSC (`40..49`, `60..69`)
      - Tug / Pilot / SAR / Port / Dredging / Law Enforcement / Military (`31..35`, `50..59`)
      - Fishing / Sailing / Pleasure (`30`, `36`, `37`)
    Returns `0.0` for Cargo (`70..79`), Tanker (`80..89`), Other (`90..99`), or Unknown.

    Args:
        ship_type: Numeric AIS ship type code, string code, or DMA string label.

    Returns:
        `1.0` if high-maneuverability vessel, else `0.0`.
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


def check_domain(dt_s: float, sog_kn: float) -> bool:
    """Check whether step duration `dt_s` and speed `sog_kn` fall within the training domain.

    The model is trained on open-water transit steps with `dt` in `[60, 300]` seconds
    and `sog` in `(2.0, 30.0)` knots.

    Args:
        dt_s: Elapsed time between consecutive AIS fixes in seconds.
        sog_kn: Vessel speed over ground in knots.

    Returns:
        True if `(dt_s, sog_kn)` lies inside `[60.0, 300.0]s x (2.0, 30.0) kn`, else False.

    Raises:
        ValueError: If `dt_s` or `sog_kn` is NaN or infinite.
    """
    dt_val = float(dt_s)
    sog_val = float(sog_kn)
    if not (math.isfinite(dt_val) and math.isfinite(sog_val)):
        raise ValueError(f"Non-finite domain input: dt_s={dt_s!r}, sog_kn={sog_kn!r}")
    return (VALID_DT_MIN_S <= dt_val <= VALID_DT_MAX_S) and (
        VALID_SOG_MIN_KN < sog_val < VALID_SOG_MAX_KN
    )


def load_model(weights_path: Optional[str] = None, refresh: bool = False) -> Dict[str, Any]:
    """Load and cache exported MLP weights and feature scaler parameters from JSON.

    Args:
        weights_path: Optional path to `ship_motion_mlp.json`. Defaults to
            `os.environ.get("KAIKU_MLP_WEIGHTS")` or `weights/ship_motion_mlp.json`.
        refresh: If True, bypass the in-memory cache and re-read from disk.

    Returns:
        Parsed model dictionary containing `feature_names`, `scaler`, `layers`,
        `eps`, `softplus_threshold`, and `self_check_vectors`.

    Raises:
        FileNotFoundError: If the resolved weights file does not exist.
    """
    resolved_default = os.environ.get("KAIKU_MLP_WEIGHTS") or DEFAULT_WEIGHTS_PATH
    path = os.path.abspath(weights_path or resolved_default)
    if not refresh and path in _MODEL_CACHE:
        return _MODEL_CACHE[path]
    if not os.path.exists(path):
        raise FileNotFoundError(f"Model weights file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data: Dict[str, Any] = json.load(fh)
    _MODEL_CACHE[path] = data
    return data


def _softplus(x: float, threshold: float = 20.0) -> float:
    """Compute numerically stable softplus matching `torch.nn.functional.softplus`.

    Args:
        x: Scalar pre-activation value.
        threshold: Linear regime cutoff used by PyTorch `F.softplus` to prevent
            exponential overflow.

    Returns:
        Strictly positive scalar `log(1 + exp(x))`.
    """
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
    """Compute an affine transformation `y = W @ x + b` in pure Python.

    Args:
        x: Input vector of shape `(in_features,)`.
        weight: Weight matrix of shape `(out_features, in_features)`.
        bias: Bias vector of shape `(out_features,)`.

    Returns:
        Output vector of shape `(out_features,)`.
    """
    out: List[float] = []
    for row_w, b in zip(weight, bias):
        acc = float(b)
        for xi, wi in zip(x, row_w):
            acc += float(xi) * float(wi)
        out.append(acc)
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

    model = model_data if model_data is not None else load_model(weights_path)
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
    """Extract and validate an ordered 1D feature vector of shape `(len(feature_names),)` from a dict or sequence.

    Args:
        features_dict_or_list: Mapping of feature names to numeric values or an
            ordered sequence matching `feature_names` (supports 8-feature v1, 11-feature v2, and 14-feature v3).
        feature_names: Ordered sequence of expected feature names read dynamically from JSON.

    Returns:
        Ordered list of finite floats of length `len(feature_names)`.

    Raises:
        KeyError: If a required feature name is missing from a dict input.
        ValueError: If sequence length mismatches `feature_names` or any value is NaN/Inf.
    """
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
            (supports 8-feature v1, 11-feature v2, and 14-feature v3).
        weights_path: Optional path override to `ship_motion_mlp.json`.
        model_data: Optional pre-loaded model dict from `load_model()`.

    Returns:
        4-tuple `(mu_dv_east, mu_dv_north, std_east, std_north)` in knots.

    Raises:
        ValueError: If any input feature is NaN or infinite.
    """
    model = model_data if model_data is not None else load_model(weights_path)
    feature_names: Sequence[str] = model["feature_names"]
    raw_x = _extract_feature_vector(features_dict_or_list, feature_names)

    mean: Sequence[float] = model["scaler"]["mean"]
    std: Sequence[float] = model["scaler"]["std"]
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


def _run_self_check(weights_path: Optional[str] = None) -> int:
    """Verify stdlib-only execution, input guards, and `< 1e-5` numerical parity with PyTorch.

    Args:
        weights_path: Optional path override to `ship_motion_mlp.json`.

    Returns:
        Process exit code (`0` on success, `1` on failure).
    """
    forbidden = [m for m in ("torch", "numpy", "pandas", "scipy") if m in sys.modules]
    if forbidden:
        print(f"FAIL: External modules loaded in self-check: {forbidden}", file=sys.stderr)
        return 1

    model = load_model(weights_path)
    feature_names: List[str] = model["feature_names"]
    resolved_default = os.environ.get("KAIKU_MLP_WEIGHTS") or DEFAULT_WEIGHTS_PATH
    resolved_path = os.path.abspath(weights_path or resolved_default)
    print(f"[mlp_infer] Loaded weights from: {resolved_path}")
    print(f"[mlp_infer] Python executable:   {sys.executable} ({sys.version.split()[0]})")
    print(f"[mlp_infer] Architecture:        {model.get('architecture', '8->64->64->4')}")
    print(f"[mlp_infer] Features ({len(feature_names)}):       {feature_names}")

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

    print(f"[mlp_infer] Checked {len(vectors)} PyTorch reference vectors | max_abs_diff = {max_diff:.3e}")
    if max_diff >= 1e-5:
        print(f"FAIL: max_abs_diff {max_diff:.3e} >= 1e-5 tolerance", file=sys.stderr)
        return 1

    # 1. Verify NaN and Inf rejection in predict() and anomaly_score()
    sample_feats = list(vectors[0]["features"])
    for bad_val in (float("nan"), float("inf"), float("-inf")):
        bad_feats = list(sample_feats)
        bad_feats[0] = bad_val
        try:
            predict(bad_feats, model_data=model)
            print(f"FAIL: predict() did not raise ValueError on {bad_val}", file=sys.stderr)
            return 1
        except ValueError:
            pass

        bad_dict = dict(zip(feature_names, sample_feats))
        bad_dict[feature_names[3]] = bad_val
        try:
            predict(bad_dict, model_data=model)
            print(f"FAIL: predict(dict) did not raise ValueError on {bad_val}", file=sys.stderr)
            return 1
        except ValueError:
            pass

        try:
            anomaly_score(bad_val, 0.0, (0.0, 0.0, 0.2, 0.2))
            print(f"FAIL: anomaly_score() did not raise ValueError on {bad_val}", file=sys.stderr)
            return 1
        except ValueError:
            pass

        try:
            anomaly_score(0.0, 0.0, (0.0, 0.0, bad_val, 0.2))
            print(f"FAIL: anomaly_score() did not raise ValueError on pred {bad_val}", file=sys.stderr)
            return 1
        except ValueError:
            pass

    # 2. Verify zero-std safety (clamped variance prevents ZeroDivisionError)
    z_e0, z_n0, rad_z0, nll0, anom0 = anomaly_score(0.1, -0.1, (0.0, 0.0, 0.0, 0.0))
    if not (math.isfinite(z_e0) and math.isfinite(z_n0) and math.isfinite(rad_z0) and math.isfinite(nll0) and anom0):
        print("FAIL: Zero-std clamping check failed in anomaly_score()", file=sys.stderr)
        return 1

    # 3. Verify rotation-invariant 2D radial_z > 2.447746830680816 threshold
    # (1.8, 1.8) has |z_e| <= 1.96 and |z_n| <= 1.96, but radial_z = sqrt(6.48) = 2.5456 > 2.4477
    _, _, rz_diag_out, _, is_anom_diag_out = anomaly_score(1.8, 1.8, (0.0, 0.0, 1.0, 1.0))
    _, _, rz_diag_in, _, is_anom_diag_in = anomaly_score(1.6, 1.6, (0.0, 0.0, 1.0, 1.0))
    if not is_anom_diag_out or is_anom_diag_in:
        print(
            f"FAIL: Rotation-invariant 95% CI check failed: "
            f"rz_out={rz_diag_out:.3f} (anom={is_anom_diag_out}), "
            f"rz_in={rz_diag_in:.3f} (anom={is_anom_diag_in})",
            file=sys.stderr,
        )
        return 1

    # 4. Verify check_domain() and lookup_flow()
    if not check_domain(65.0, 11.2) or check_domain(15.0, 11.2) or check_domain(65.0, 0.5):
        print("FAIL: check_domain() validation failed.", file=sys.stderr)
        return 1

    if lookup_flow(float("nan"), 25.0, 10.0, 0.0, model) != (0.0, 0.0, 0.0):
        print("FAIL: lookup_flow() did not return (0.0, 0.0, 0.0) on NaN input.", file=sys.stderr)
        return 1
    if lookup_flow(0.0, 0.0, 10.0, 0.0, model) != (0.0, 0.0, 0.0):
        print("FAIL: lookup_flow() did not return (0.0, 0.0, 0.0) on OOD coordinates.", file=sys.stderr)
        return 1
    if isinstance(model.get("flow_field"), dict) and model["flow_field"].get("cells"):
        first_key = next(iter(model["flow_field"]["cells"]))
        lb_s, lob_s, oct_s = [int(x) for x in first_key.split(",")]
        lat_st = float(model["flow_field"].get("lat_step", 0.02))
        lon_st = float(model["flow_field"].get("lon_step", 0.04))
        ang_rad = math.radians(oct_s * 45.0)
        _, _, hf = lookup_flow(
            (lb_s + 0.5) * lat_st,
            (lob_s + 0.5) * lon_st,
            10.0 * math.sin(ang_rad),
            10.0 * math.cos(ang_rad),
            model,
        )
        if hf != 1.0:
            print("FAIL: lookup_flow() failed to match known flow_field cell.", file=sys.stderr)
            return 1

    pred0 = predict(sample_feats, model_data=model)
    norm_scores = anomaly_score(pred0[0], pred0[1], pred0)
    drag_scores = anomaly_score(pred0[0] - 2.8, pred0[1] - 1.9, pred0)
    print(
        f"[mlp_infer] Normal step check -> radial_z={norm_scores[2]:.2f}, "
        f"nll={norm_scores[3]:.3f}, is_anomaly_95ci={norm_scores[4]}"
    )
    print(
        f"[mlp_infer] Anchor-drag check -> radial_z={drag_scores[2]:.2f}, "
        f"nll={drag_scores[3]:.3f}, is_anomaly_95ci={drag_scores[4]}"
    )
    print(
        "[mlp_infer] Guards verified:   NaN/Inf -> ValueError, std=0 clamped (1e-12 var), "
        f"radial_z > {RADIAL_Z_95CI:.4f} (sqrt(chi2_2,0.95))"
    )
    if norm_scores[4] or not drag_scores[4]:
        print("FAIL: Unexpected anomaly flag behavior on normal vs drag test.", file=sys.stderr)
        return 1

    print("[mlp_infer] SELF-CHECK PASSED (zero external dependencies, < 1e-5 parity with PyTorch).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KAIKU pure-Python ship-motion MLP inference.")
    parser.add_argument("--weights", default=None, help="Path to ship_motion_mlp.json")
    parser.add_argument("--self-check", action="store_true", help="Run parity & anomaly self-check")
    args = parser.parse_args()
    if args.self_check:
        sys.exit(_run_self_check(args.weights))
    parser.print_help()
