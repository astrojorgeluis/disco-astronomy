#!/usr/bin/env python3
"""Train DiscoNet for DISCO geometry priors.

Uses shared preprocess from ``disco.core.cnn_preprocess`` (same beam / labels
as inference). Saves ``disco_model_stable.pth`` compatible with the package.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from scipy.ndimage import gaussian_filter
from scipy.signal import convolve2d
from torch.utils.data import DataLoader, Dataset, Subset

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from disco.core.cnn_inference import DiscoNet  # noqa: E402
from disco.core.cnn_preprocess import (  # noqa: E402
    CENTER_SCALE,
    IMG_SIZE,
    NUM_OUTPUTS,
    OUTPUT_NAMES,
    elliptical_beam_map,
    encode_labels,
    normalize_percentile,
    scale_map,
    stack_cnn_channels,
)

DEFAULT_SAVE = "disco_model_stable.pth"


class SyntheticDataset(Dataset):
    def __init__(self, num_samples=20000, img_size=IMG_SIZE, seed=42):
        self.num_samples = num_samples
        self.img_size = img_size
        self.rng = np.random.RandomState(seed)
        print(f"  [SyntheticDataset] Generating {num_samples} samples ...", flush=True)
        self.images, self.labels = self._generate()
        import gc

        gc.collect()
        print("  [SyntheticDataset] Generation complete.", flush=True)

    @staticmethod
    def _get_beam_kernel(beam_major, beam_minor, bpa_radians, size=21):
        x_coords = np.arange(-size, size + 1)
        x_grid, y_grid = np.meshgrid(x_coords, x_coords)
        x_rotated = x_grid * np.cos(bpa_radians) + y_grid * np.sin(bpa_radians)
        y_rotated = -x_grid * np.sin(bpa_radians) + y_grid * np.cos(bpa_radians)
        kernel = np.exp(
            -(x_rotated**2 / (2 * beam_major**2 + 1e-8) + y_rotated**2 / (2 * beam_minor**2 + 1e-8))
        )
        kernel = np.maximum(kernel, 0)
        s = kernel.sum()
        return kernel / s if s > 0 else kernel

    def _generate(self):
        images = np.zeros((self.num_samples, 3, self.img_size, self.img_size), dtype=np.float32)
        labels = np.zeros((self.num_samples, NUM_OUTPUTS), dtype=np.float32)
        linear_space = np.linspace(-1, 1, self.img_size)
        x_base, y_base = np.meshgrid(linear_space, linear_space)

        for i in range(self.num_samples):
            crop_arcsec = self.rng.uniform(0.8, 5.0)
            arcsec_per_unit = crop_arcsec / 2.0

            if self.rng.rand() < 0.30:
                rout_arcsec = self.rng.uniform(1.0, min(2.0, crop_arcsec * 0.85))
            else:
                rout_arcsec = self.rng.uniform(0.05, crop_arcsec * 0.85)

            rout_val = rout_arcsec / arcsec_per_unit
            inclination = self.rng.uniform(0, 83)
            pa_degrees = self.rng.uniform(0, 180)
            pa_radians = np.radians(pa_degrees)
            cos_inclination = max(np.cos(np.radians(inclination)), 0.04)

            dx = self.rng.uniform(-0.12, 0.12)
            dy = self.rng.uniform(-0.12, 0.12)
            x_shifted = x_base - dx
            y_shifted = y_base - dy

            r_major = -x_shifted * np.sin(pa_radians) + y_shifted * np.cos(pa_radians)
            r_minor = x_shifted * np.cos(pa_radians) + y_shifted * np.sin(pa_radians)
            r_minor_deprojected = r_minor / cos_inclination
            radii = np.sqrt(r_major**2 + r_minor_deprojected**2)

            morphology = self.rng.choice(["smooth", "simple", "complex"], p=[0.25, 0.40, 0.35])
            if morphology == "smooth":
                num_gaps = 0
            elif morphology == "simple":
                num_gaps = self.rng.randint(1, 3)
            else:
                num_gaps = self.rng.randint(3, 6)

            gamma = self.rng.uniform(0.3, 1.0)
            critical_radius = max(rout_val * self.rng.uniform(0.35, 0.75), 0.02)
            safe_radii = np.maximum(radii, 0.001)

            sigma = (safe_radii / critical_radius) ** (-gamma) * np.exp(
                -(safe_radii / critical_radius) ** (2.0 - gamma)
            )
            sigma = np.clip(sigma / (sigma.max() + 1e-10), 0, 1)

            t_zero = self.rng.uniform(40, 160)
            q_factor = self.rng.uniform(0.35, 0.55)
            tau = self.rng.uniform(1.5, 10.0)
            radial_temp = np.clip(
                t_zero * (safe_radii / max(rout_val * 0.05, 0.001)) ** (-q_factor), 5, 2000
            )
            disk_image = radial_temp * (1.0 - np.exp(-tau * sigma))

            rmin_val = 0.0
            if self.rng.rand() < 0.30:
                rmin_val = self.rng.uniform(0.05, rout_val * 0.55)
                rim_width = rmin_val * self.rng.uniform(0.20, 0.45)
                taper = 0.5 * (1.0 + np.tanh((safe_radii - rmin_val) / (rim_width + 1e-5)))
                cavity_depth = self.rng.uniform(0.70, 0.95)
                disk_image *= 1.0 - cavity_depth * (1.0 - taper)

            feature_radii = [rmin_val]
            for _ in range(num_gaps):
                gap_start = max(rmin_val + 0.02, rout_val * 0.08)
                gap_radius = self.rng.uniform(gap_start, rout_val * 0.88)
                if any(abs(gap_radius - feature) < rout_val * 0.10 for feature in feature_radii):
                    continue
                feature_radii.append(gap_radius)
                gap_width = gap_radius * self.rng.uniform(0.04, 0.14)
                gap_depth = self.rng.uniform(0.35, 0.80)
                disk_image *= 1.0 - gap_depth * np.exp(
                    -0.5 * ((safe_radii - gap_radius) / (gap_width + 1e-5)) ** 2
                )
                if self.rng.rand() < 0.80:
                    ring_radius = gap_radius + gap_width * self.rng.uniform(0.8, 2.5)
                    if ring_radius < rout_val * 0.95:
                        ring_width = gap_width * self.rng.uniform(0.5, 1.5)
                        ring_amplitude = self.rng.uniform(0.08, 0.40) * (np.max(disk_image) + 1e-15)
                        disk_image += ring_amplitude * np.exp(
                            -0.5 * ((safe_radii - ring_radius) / (ring_width + 1e-5)) ** 2
                        )

            exponent = self.rng.uniform(1.5, 3.5)
            disk_image *= np.exp(-(safe_radii / (rout_val + 1e-5)) ** exponent)
            disk_image = np.maximum(disk_image, 0)

            beam_major = self.rng.uniform(0.3, 3.5)
            beam_minor = beam_major * self.rng.uniform(0.4, 0.95)
            beam_pa = self.rng.uniform(0, np.pi)
            target_snr = self.rng.uniform(5, 200)
            beam_kernel = self._get_beam_kernel(beam_major, beam_minor, beam_pa)

            blurred_image = convolve2d(
                disk_image.astype(np.float64), beam_kernel.astype(np.float64), mode="same"
            )
            peak_flux = max(np.max(blurred_image), 1e-12)
            rms_noise = peak_flux / (target_snr + 1e-8)

            white_noise = self.rng.normal(0, 1, disk_image.shape)
            structured_noise = convolve2d(white_noise, beam_kernel, mode="same")
            structured_noise *= rms_noise / (np.std(structured_noise) + 1e-10)

            if self.rng.rand() < 0.50:
                low_freq_noise = gaussian_filter(
                    self.rng.normal(0, 1, disk_image.shape), sigma=self.rng.uniform(4, 16)
                )
                low_freq_noise *= (
                    self.rng.uniform(0.05, 0.20) * rms_noise / (np.std(low_freq_noise) + 1e-10)
                )
                structured_noise = structured_noise + low_freq_noise

            final_image = blurred_image + structured_noise
            normalized_img = normalize_percentile(final_image)

            if self.rng.rand() < 0.5:
                normalized_img = np.fliplr(normalized_img).copy()
                pa_degrees = (180.0 - pa_degrees) % 180.0
                dx = -dx
                beam_pa = np.pi - beam_pa
            if self.rng.rand() < 0.5:
                normalized_img = np.flipud(normalized_img).copy()
                pa_degrees = (180.0 - pa_degrees) % 180.0
                dy = -dy
                beam_pa = -beam_pa

            cell_as = crop_arcsec / self.img_size
            bmaj_as = beam_major * 2.355 * cell_as
            bmin_as = beam_minor * 2.355 * cell_as
            beam_map = elliptical_beam_map(
                bmaj_as, bmin_as, np.degrees(beam_pa), cell_as, self.img_size
            )
            scale = scale_map(bmaj_as, crop_arcsec, self.img_size)

            images[i] = stack_cnn_channels(normalized_img, beam_map, scale)
            labels[i] = encode_labels(inclination, pa_degrees, dx_fov=dx, dy_fov=dy)

            if (i + 1) % 5000 == 0:
                print(f"    {i + 1}/{self.num_samples}", flush=True)

        return torch.from_numpy(images), torch.from_numpy(labels)

    def __len__(self):
        return self.num_samples

    def __getitem__(self, idx):
        return self.images[idx], self.labels[idx]


def custom_loss(predictions, targets):
    loss_inclination = nn.functional.l1_loss(predictions[:, 0], targets[:, 0])
    loss_pa = nn.functional.l1_loss(predictions[:, 1:3], targets[:, 1:3])
    loss_center = nn.functional.l1_loss(predictions[:, 3:5], targets[:, 3:5])
    return 3.0 * loss_inclination + 2.0 * loss_pa + 0.5 * loss_center


def mixup_batch(inputs, targets, alpha=0.25):
    """Mix images; do not blend PA sin/cos targets (breaks angular geometry)."""
    lambda_val = float(np.random.beta(alpha, alpha))
    lambda_val = max(lambda_val, 1.0 - lambda_val)
    indices = torch.randperm(inputs.size(0), device=inputs.device)

    mixed_inputs = lambda_val * inputs + (1.0 - lambda_val) * inputs[indices]
    mixed_targets = targets.clone()
    mixed_targets[:, 0] = lambda_val * targets[:, 0] + (1.0 - lambda_val) * targets[indices, 0]
    mixed_targets[:, 1:3] = targets[:, 1:3]
    mixed_targets[:, 3:5] = lambda_val * targets[:, 3:5] + (1.0 - lambda_val) * targets[indices, 3:5]
    return mixed_inputs, mixed_targets


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--synthetic-samples", type=int, default=20000)
    p.add_argument("--epochs", type=int, default=80)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--patience", type=int, default=15, help="Early stopping patience (0=off)")
    p.add_argument("--amp", action="store_true", help="Enable CUDA AMP")
    p.add_argument("--resume", type=str, default="", help="Checkpoint to resume")
    p.add_argument("--save", type=str, default=DEFAULT_SAVE)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[INFO] Device: {device}")
    print(f"[INFO] IMG_SIZE={IMG_SIZE}  Epochs={args.epochs}  Batch={args.batch_size}")

    print("\n[INFO] Generating synthetic dataset ...")
    synth = SyntheticDataset(num_samples=args.synthetic_samples, img_size=IMG_SIZE, seed=args.seed)
    n_synth_val = max(int(len(synth) * 0.10), 1)
    synth_idx = np.arange(len(synth))
    rng = np.random.RandomState(args.seed)
    rng.shuffle(synth_idx)
    val_s = synth_idx[:n_synth_val].tolist()
    tr_s = synth_idx[n_synth_val:].tolist()
    train_ds = Subset(synth, tr_s)
    val_ds = Subset(synth, val_s)
    print(f"\n[INFO] Train: {len(train_ds)}  |  Val: {len(val_ds)}")

    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0, pin_memory=True
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0, pin_memory=True
    )

    model = DiscoNet(n_out=NUM_OUTPUTS).to(device)
    print(f"[INFO] Parameters: {sum(p.numel() for p in model.parameters() if p.requires_grad)/1e6:.2f}M")

    optimizer = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-3)
    start_epoch = 1
    best_val = float("inf")

    if args.resume and os.path.isfile(args.resume):
        ckpt = torch.load(args.resume, map_location=device, weights_only=False)
        state = ckpt["model_state"] if isinstance(ckpt, dict) else ckpt
        model.load_state_dict(state)
        if isinstance(ckpt, dict):
            start_epoch = int(ckpt.get("epoch", 0)) + 1
            best_val = float(ckpt.get("val_loss", best_val))
        print(f"[INFO] Resumed from {args.resume} (epoch {start_epoch})")

    def lr_schedule(epoch_idx):
        warmup = 5
        if epoch_idx < warmup:
            return (epoch_idx + 1) / warmup
        progress = (epoch_idx - warmup) / max(args.epochs - warmup, 1)
        return 0.10 + 0.90 * 0.5 * (1 + np.cos(np.pi * progress))

    scheduler = optim.lr_scheduler.LambdaLR(optimizer, lr_schedule)
    scaler = torch.amp.GradScaler("cuda", enabled=bool(args.amp and device.type == "cuda"))
    patience_left = args.patience

    print(f"\n[INFO] Training ...\n")
    print(f"{'Epoch':>6} | {'Train':>8} | {'Val':>8} | {'MAE_i':>7} | {'MAE_PA':>7} | {'MAE_c':>7} | LR")
    print("-" * 72)

    for epoch in range(start_epoch, args.epochs + 1):
        model.train()
        train_loss = 0.0
        for inputs, targets in train_loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            if np.random.rand() < 0.50:
                inputs, targets = mixup_batch(inputs, targets)

            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=scaler.is_enabled()):
                preds = model(inputs)
                loss = custom_loss(preds, targets)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            scaler.step(optimizer)
            scaler.update()
            train_loss += loss.item()

        model.eval()
        val_loss = 0.0
        err_i, err_pa, err_c = [], [], []
        with torch.no_grad():
            for inputs, targets in val_loader:
                inputs = inputs.to(device)
                targets = targets.to(device)
                preds = model(inputs)
                val_loss += custom_loss(preds, targets).item()

                pred_incl = preds[:, 0].cpu().numpy() * 90.0
                true_incl = targets[:, 0].cpu().numpy() * 90.0
                pred_pa = (
                    np.degrees(np.arctan2(preds[:, 1].cpu().numpy(), preds[:, 2].cpu().numpy())) / 2.0
                ) % 180.0
                true_pa = (
                    np.degrees(
                        np.arctan2(targets[:, 1].cpu().numpy(), targets[:, 2].cpu().numpy())
                    )
                    / 2.0
                ) % 180.0
                err_i.extend(np.abs(pred_incl - true_incl).tolist())
                dpa = np.abs(pred_pa - true_pa)
                err_pa.extend(np.minimum(dpa, 180.0 - dpa).tolist())

                pred_c = preds[:, 3:5].cpu().numpy() * CENTER_SCALE
                true_c = targets[:, 3:5].cpu().numpy() * CENTER_SCALE
                err_c.extend(np.linalg.norm(pred_c - true_c, axis=1).tolist())

        avg_tr = train_loss / max(len(train_loader), 1)
        avg_va = val_loss / max(len(val_loader), 1)
        mae_i = float(np.mean(err_i)) if err_i else float("nan")
        mae_pa = float(np.mean(err_pa)) if err_pa else float("nan")
        mae_c = float(np.mean(err_c)) if err_c else float("nan")
        lr = optimizer.param_groups[0]["lr"]
        scheduler.step()

        marker = " <-" if avg_va < best_val else ""
        ts = datetime.now().strftime("%H:%M:%S")
        print(
            f"[{ts}] {epoch:3d}/{args.epochs} | {avg_tr:.4f}   | {avg_va:.4f}   | "
            f"{mae_i:5.1f}deg  | {mae_pa:5.1f}deg  | {mae_c:6.3f}  | {lr:.2e}{marker}"
        )

        if avg_va < best_val:
            best_val = avg_va
            patience_left = args.patience
            torch.save(
                {
                    "epoch": epoch,
                    "model_state": model.state_dict(),
                    "val_loss": best_val,
                    "img_size": IMG_SIZE,
                    "n_out": NUM_OUTPUTS,
                    "outputs": OUTPUT_NAMES,
                    "mae_incl_deg": mae_i,
                    "mae_pa_deg": mae_pa,
                    "mae_center_fov": mae_c,
                },
                args.save,
            )
        elif args.patience > 0:
            patience_left -= 1
            if patience_left <= 0:
                print(f"[INFO] Early stopping at epoch {epoch}")
                break

    print(f"\n[DONE] Best model -> '{args.save}'  (val={best_val:.5f})")
    print(f"[INFO] Outputs: {OUTPUT_NAMES}")
    pkg_models = _ROOT / "disco" / "models" / "disco_model_stable.pth"
    print(f"[INFO] Install for package use: cp {args.save} {pkg_models}")


if __name__ == "__main__":
    main()
