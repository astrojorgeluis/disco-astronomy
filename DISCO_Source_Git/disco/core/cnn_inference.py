import numpy as np
import torch
import torch.nn as nn

from disco.core.cnn_preprocess import (
    IMG_SIZE,
    NUM_OUTPUTS,
    decode_labels,
    elliptical_beam_map,
    normalize_percentile,
    resize_to_square,
    scale_map,
    stack_cnn_channels,
)


class ResBlock(nn.Module):
    def __init__(self, ch):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(ch, ch, 3, padding=1, bias=False), nn.BatchNorm2d(ch), nn.ReLU(inplace=True),
            nn.Conv2d(ch, ch, 3, padding=1, bias=False), nn.BatchNorm2d(ch),
        )
        self.act = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.act(x + self.net(x))


class DiscoNet(nn.Module):
    def __init__(self, n_out=NUM_OUTPUTS):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1, bias=False),
            nn.BatchNorm2d(32), nn.ReLU(inplace=True))
        self.enc1 = nn.Sequential(ResBlock(32),  nn.Conv2d(32,  64,  3, stride=2, padding=1, bias=False), nn.BatchNorm2d(64),  nn.ReLU(inplace=True))
        self.enc2 = nn.Sequential(ResBlock(64),  nn.Conv2d(64,  128, 3, stride=2, padding=1, bias=False), nn.BatchNorm2d(128), nn.ReLU(inplace=True))
        self.enc3 = nn.Sequential(ResBlock(128), nn.Conv2d(128, 256, 3, stride=2, padding=1, bias=False), nn.BatchNorm2d(256), nn.ReLU(inplace=True))
        self.enc4 = nn.Sequential(ResBlock(256), nn.Conv2d(256, 512, 3, stride=2, padding=1, bias=False), nn.BatchNorm2d(512), nn.ReLU(inplace=True))
        self.enc5 = nn.Sequential(ResBlock(512), nn.Conv2d(512, 512, 3, stride=2, padding=1, bias=False), nn.BatchNorm2d(512), nn.ReLU(inplace=True))
        self.pool = nn.AdaptiveAvgPool2d(4)
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(512 * 4 * 4, 1024), nn.ReLU(inplace=True), nn.Dropout(0.45),
            nn.Linear(1024, 512),          nn.ReLU(inplace=True), nn.Dropout(0.30),
            nn.Linear(512, n_out),
        )

    def forward(self, x):
        x = self.stem(x)
        for enc in [self.enc1, self.enc2, self.enc3, self.enc4, self.enc5]:
            x = enc(x)
        return self.head(self.pool(x))


def prepare_cnn_inputs(data, header, pixel_scale, cx, cy, search_rad, img_size=IMG_SIZE):
    """Crop / resize / normalize + beam/scale channels for DiscoNet.

    Returns
    -------
    tensor_chw : (3, H, W) float32 ndarray or None if crop is empty
    crop_half_pix : float
        Half-width of the native crop in pixels (for FOV→pixel conversion).
    """
    search_rad_pix = int(search_rad / pixel_scale)
    crop_rad = int(search_rad_pix * 1.5)

    y_min = max(0, int(cy - crop_rad))
    y_max = min(data.shape[0], int(cy + crop_rad))
    x_min = max(0, int(cx - crop_rad))
    x_max = min(data.shape[1], int(cx + crop_rad))
    crop = data[y_min:y_max, x_min:x_max].astype(np.float64)
    if crop.shape[0] == 0 or crop.shape[1] == 0:
        return None, float(crop_rad)

    target_size = crop_rad * 2
    if target_size <= 0:
        return None, float(crop_rad)
    if crop.shape[0] != target_size or crop.shape[1] != target_size:
        pad_y = max(0, target_size - crop.shape[0])
        pad_x = max(0, target_size - crop.shape[1])
        crop = np.pad(crop, ((0, pad_y), (0, pad_x)), mode="constant")

    if crop.shape[0] == 0 or crop.shape[1] == 0:
        return None, float(crop_rad)

    img_r = resize_to_square(crop, img_size)
    img_norm = normalize_percentile(img_r)

    bmaj_arcsec = float(header.get("BMAJ", 0) or 0) * 3600.0
    bmin_arcsec = float(header.get("BMIN", 0) or 0) * 3600.0
    bpa_deg = float(header.get("BPA", 0) or 0)

    field_as = crop_rad * 2 * pixel_scale
    cell_eff = field_as / img_size

    if bmaj_arcsec <= 0:
        raise ValueError(
            "The FITS file does not contain valid beam information (BMAJ). "
            "CNN inference requires known resolution."
        )
    if bmin_arcsec <= 0:
        bmin_arcsec = bmaj_arcsec

    beam = elliptical_beam_map(bmaj_arcsec, bmin_arcsec, bpa_deg, cell_eff, img_size)
    scale = scale_map(bmaj_arcsec, field_as, img_size)
    return stack_cnn_channels(img_norm, beam, scale), float(crop_rad)


def predict_with_cnn(data, header, pixel_scale, cx, cy, search_rad, model):
    """CNN geometry prior.

    Returns
    -------
    cnn_incl, cnn_pa, dx_pix, dy_pix
        Offsets are in native image pixels relative to ``(cx, cy)``.
    """
    try:
        chw, crop_half_pix = prepare_cnn_inputs(
            data, header, pixel_scale, cx, cy, search_rad
        )
    except ValueError:
        raise

    if chw is None:
        return 0.0, 0.0, 0.0, 0.0

    tensor_in = torch.tensor(chw[np.newaxis], dtype=torch.float32)

    model.eval()
    with torch.no_grad():
        out = model(tensor_in)[0].numpy()

    decoded = decode_labels(out, crop_half_pix=crop_half_pix)
    return (
        decoded["inclination"],
        decoded["pa"],
        decoded["dx_pix"],
        decoded["dy_pix"],
    )
