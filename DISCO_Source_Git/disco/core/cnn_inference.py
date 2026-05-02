import numpy as np
import torch
import torch.nn as nn
from scipy.ndimage import zoom

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
    def __init__(self, n_out=6):
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
    

def predict_with_cnn(data, header, pixel_scale, cx, cy, search_rad, model):
    IMG_SIZE = 128

    search_rad_pix = int(search_rad / pixel_scale)
    crop_rad       = int(search_rad_pix * 1.5)

    y_min = max(0, int(cy - crop_rad))
    y_max = min(data.shape[0], int(cy + crop_rad))
    x_min = max(0, int(cx - crop_rad))
    x_max = min(data.shape[1], int(cx + crop_rad))
    crop  = data[y_min:y_max, x_min:x_max].astype(np.float64)

    target_size = crop_rad * 2
    if crop.shape[0] != target_size or crop.shape[1] != target_size:
        pad_y = max(0, target_size - crop.shape[0])
        pad_x = max(0, target_size - crop.shape[1])
        crop  = np.pad(crop, ((0, pad_y), (0, pad_x)), mode='constant')

    if crop.shape[0] == 0 or crop.shape[1] == 0:
        return 0.0, 0.0, 0.0

    zoom_y = IMG_SIZE / crop.shape[0]
    zoom_x = IMG_SIZE / crop.shape[1]
    img_r  = zoom(crop, (zoom_y, zoom_x), order=1)
    p1, p999 = np.percentile(img_r, 1), np.percentile(img_r, 99.9)
    img_norm = np.clip((img_r - p1) / (p999 - p1 + 1e-8), 0, 1).astype(np.float32)

    bmaj_arcsec = header.get('BMAJ', 0) * 3600
    bmin_arcsec = header.get('BMIN', 0) * 3600
    bpa_deg     = header.get('BPA',  0)

    field_as   = crop_rad * 2 * pixel_scale
    cell_eff   = field_as / IMG_SIZE

    beam_map = np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)
    if bmaj_arcsec > 0 and bmin_arcsec > 0:
        sigma_maj = (bmaj_arcsec / cell_eff) / 2.355
        sigma_min = (bmin_arcsec / cell_eff) / 2.355
        bpa_rad   = np.radians(bpa_deg)
        c = IMG_SIZE // 2
        y_g, x_g = np.ogrid[:IMG_SIZE, :IMG_SIZE]
        Xr = (x_g - c) * np.cos(bpa_rad) + (y_g - c) * np.sin(bpa_rad)
        Yr = -(x_g - c) * np.sin(bpa_rad) + (y_g - c) * np.cos(bpa_rad)
        g  = np.exp(-(Xr**2 / (2 * sigma_maj**2 + 1e-8) +
                      Yr**2 / (2 * sigma_min**2 + 1e-8)))
        mx = g.max()
        if mx > 0:
            beam_map = (g / mx).astype(np.float32)

    if bmaj_arcsec <= 0:
        raise ValueError("The FITS file does not contain valid beam information (BMAJ). CNN inference requires known resolution.")
    beam_fwhm_as = bmaj_arcsec
    scale_val    = float(np.clip(beam_fwhm_as / (field_as + 1e-6), 0, 1))
    scale_map    = np.full((IMG_SIZE, IMG_SIZE), scale_val, dtype=np.float32)

    tensor_in = torch.tensor(
        np.stack([img_norm, beam_map, scale_map], axis=0)[np.newaxis],
        dtype=torch.float32
    )

    model.eval()
    with torch.no_grad():
        out = model(tensor_in)[0].numpy()

    cnn_incl = float(np.clip(out[0] * 90.0, 0.0, 85.0))
    cnn_pa   = float((np.degrees(np.arctan2(out[1], out[2])) / 2.0) % 180.0)

    return cnn_incl, cnn_pa