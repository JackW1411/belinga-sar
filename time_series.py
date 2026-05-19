import numpy as np
import json
import rasterio
import os
from datetime import datetime
from pathlib import Path

STACK_DIR  = "outputs/stack"
VV_STACK   = f"{STACK_DIR}/vv_stack.npy"
VH_STACK   = f"{STACK_DIR}/vh_stack.npy"
DATES_FILE = f"{STACK_DIR}/dates.json"

# Confirmed after first scene -- update if different
H, W = 2570, 1630

PRE_END   = datetime(2021, 1, 1)
THRESHOLD = 0.64  # dB, Carstairs et al. 2022


def init_stacks(n_scenes):
    os.makedirs(STACK_DIR, exist_ok=True)
    vv = np.lib.format.open_memmap(VV_STACK, mode='w+', dtype='float32', shape=(n_scenes, H, W))
    vh = np.lib.format.open_memmap(VH_STACK, mode='w+', dtype='float32', shape=(n_scenes, H, W))
    return vv, vh


def load_stacks(n_scenes):
    vv = np.lib.format.open_memmap(VV_STACK, mode='r+', dtype='float32', shape=(n_scenes, H, W))
    vh = np.lib.format.open_memmap(VH_STACK, mode='r+', dtype='float32', shape=(n_scenes, H, W))
    return vv, vh


def pad_or_crop(arr):
    h, w = arr.shape
    out = np.full((H, W), np.nan, dtype=np.float32)
    out[:min(h, H), :min(w, W)] = arr[:min(h, H), :min(w, W)]
    return out


def write_scene(vv_stack, vh_stack, idx, vv_db, vh_db):
    vv_stack[idx] = pad_or_crop(vv_db)
    vh_stack[idx] = pad_or_crop(vh_db)


def compute_rcr(vv_stack, vh_stack, dates):
    dates_dt = [datetime.fromisoformat(d) for d in dates]
    pre_idx  = [i for i, d in enumerate(dates_dt) if d < PRE_END]
    post_idx = [i for i, d in enumerate(dates_dt) if d >= PRE_END]

    print(f"Baseline scenes: {len(pre_idx)} | Post-disturbance: {len(post_idx)}")

    # VV only for primary disturbance index (Carstairs et al.)
    baseline_vv = np.nanmean(vv_stack[pre_idx], axis=0)

    loss_count = np.zeros((H, W), dtype=np.int16)
    for idx in post_idx:
        diff = vv_stack[idx] - baseline_vv
        loss_count += (diff < -THRESHOLD).astype(np.int16)

    # Persistent disturbance: majority of post scenes show loss
    disturbance = loss_count > (len(post_idx) * 0.5)

    return disturbance, baseline_vv, loss_count