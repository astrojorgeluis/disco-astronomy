import os
import csv
import glob
from datetime import datetime
import numpy as np
from scipy.signal import convolve2d
from scipy.ndimage import gaussian_filter, zoom
from astropy.io import fits
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, ConcatDataset, random_split

IMG_SIZE = 128          
SIMULATIONS_DIR = "simulations"   
CATALOG_FILE = "catalogo_piloto.csv"
SYNTHETIC_SAMPLES_COUNT = 20000      
REAL_AUGMENTATION_FACTOR = 40           
EPOCHS = 80
BATCH_SIZE = 32
LEARNING_RATE = 3e-4
MODEL_SAVE_PATH = "disk_model_stable.pth"
NUM_OUTPUTS = 5   

BEAM_MAS = {
    "alma.cycle9.5.cfg": 130,
    "alma.cycle9.6.cfg": 80,
    "alma.cycle9.7.cfg": 50,
    "alma.cycle9.8.cfg": 28,
    "alma.cycle9.9.cfg": 18,
}

class ResBlock(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels), 
            nn.ReLU(inplace=True),
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
        )
        self.activation = nn.ReLU(inplace=True)

    def forward(self, x): 
        return self.activation(x + self.network(x))

class DiskNet(nn.Module):
    def __init__(self, num_outputs=6):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1, bias=False),  
            nn.BatchNorm2d(32), 
            nn.ReLU(inplace=True),
        )

        self.encoder1 = nn.Sequential(
            ResBlock(32),
            nn.Conv2d(32, 64, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(64),  
            nn.ReLU(inplace=True)
        )
        self.encoder2 = nn.Sequential(
            ResBlock(64),
            nn.Conv2d(64, 128, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(128), 
            nn.ReLU(inplace=True)
        )
        self.encoder3 = nn.Sequential(
            ResBlock(128),
            nn.Conv2d(128, 256, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(256), 
            nn.ReLU(inplace=True)
        )
        self.encoder4 = nn.Sequential(
            ResBlock(256),
            nn.Conv2d(256, 512, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(512), 
            nn.ReLU(inplace=True)
        )
        self.encoder5 = nn.Sequential(
            ResBlock(512),
            nn.Conv2d(512, 512, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(512), 
            nn.ReLU(inplace=True)
        )

        self.pooling = nn.AdaptiveAvgPool2d(4)

        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(512 * 4 * 4, 1024), 
            nn.ReLU(inplace=True), 
            nn.Dropout(0.45),
            nn.Linear(1024, 512),          
            nn.ReLU(inplace=True), 
            nn.Dropout(0.30),
            nn.Linear(512, num_outputs),
        )

    def forward(self, x):
        x = self.stem(x)
        for encoder in [self.encoder1, self.encoder2, self.encoder3, self.encoder4, self.encoder5]:
            x = encoder(x)
        x = self.pooling(x)
        return self.head(x)

def fits_to_tensor(image_data, img_size=IMG_SIZE):
    data = image_data.astype(np.float64)
    if data.shape[0] != img_size or data.shape[1] != img_size:
        zoom_y = img_size / data.shape[0]
        zoom_x = img_size / data.shape[1]
        data = zoom(data, (zoom_y, zoom_x), order=1)
    
    percentile_1 = np.percentile(data, 1)
    percentile_999 = np.percentile(data, 99.9)
    normalized_data = np.clip((data - percentile_1) / (percentile_999 - percentile_1 + 1e-8), 0, 1).astype(np.float32)
    return normalized_data

def make_beam_map(beam_fwhm_mas, equivalent_cell_mas, img_size=IMG_SIZE):
    sigma_pixels = (beam_fwhm_mas / 2.355) / (equivalent_cell_mas + 1e-10)
    sigma_pixels = np.clip(sigma_pixels, 0.5, img_size / 4)
    center = img_size // 2
    y_coords, x_coords = np.ogrid[:img_size, :img_size]
    gaussian_map = np.exp(-((x_coords - center)**2 + (y_coords - center)**2) / (2 * sigma_pixels**2))
    max_val = gaussian_map.max()
    return (gaussian_map / max_val).astype(np.float32) if max_val > 0 else gaussian_map.astype(np.float32)

def encode_labels(inclination, pa_degrees, r_out_arcsec=None, dx=0.0, dy=0.0):
    pa_radians = np.radians(pa_degrees)
    return np.array([
        float(inclination) / 90.0,
        float(np.sin(2.0 * pa_radians)),
        float(np.cos(2.0 * pa_radians)),
        float(dx) / 0.14,
        float(dy) / 0.14,
    ], dtype=np.float32)

def decode_labels(predictions):
    if hasattr(predictions, "cpu"):
        predictions = predictions.cpu().numpy()
    
    inclination = float(predictions[0]) * 90.0
    pa_degrees = float(np.degrees(np.arctan2(predictions[1], predictions[2])) / 2.0) % 180.0
    dx = float(predictions[3]) * 0.14
    dy = float(predictions[4]) * 0.14
    
    return dict(inclination=inclination, pa=pa_degrees, dx=dx, dy=dy)

class FITSDataset(Dataset):
    def __init__(self, simulations_dir=SIMULATIONS_DIR, catalog=CATALOG_FILE, augmentation_factor=REAL_AUGMENTATION_FACTOR, img_size=IMG_SIZE, seed=0):
        self.img_size = img_size
        self.augmentation_factor = augmentation_factor
        self.rng = np.random.RandomState(seed)

        with open(catalog, newline="") as f:
            catalog_data = list(csv.DictReader(f))
        self.catalog_dict = {row["ID"]: row for row in catalog_data}

        fits_files = sorted(glob.glob(os.path.join(simulations_dir, "**", "*_simulated.fits"), recursive=True))
        print(f"  [FITSDataset] Found {len(fits_files)} FITS files")

        self.samples = []  
        success_count = 0
        error_count = 0

        for file_path in fits_files:
            file_name = os.path.basename(file_path)
            object_id = file_name.split("_B")[0]
            row_data = self.catalog_dict.get(object_id)
            
            if row_data is None:
                error_count += 1
                continue
                
            try:
                with fits.open(file_path) as hdul:
                    image_data = hdul[0].data.squeeze().astype(np.float32)
            except Exception as e:
                print(f"  [WARN] {object_id}: {e}")
                error_count += 1
                continue

            normalized_img = fits_to_tensor(image_data, img_size)

            array_config = row_data.get("array_cfg", "alma.cycle9.7.cfg")
            beam_fwhm = BEAM_MAS.get(array_config, 50)  
            real_cell_mas = 0.0
            
            try:
                with fits.open(file_path) as hdul:
                    header = hdul[0].header
                    cdelt2 = abs(header.get("CDELT2", 0))   
                    if cdelt2 > 0:
                        real_cell_mas = cdelt2 * 3600 * 1000 
            except Exception:
                pass
                
            if real_cell_mas <= 0:
                real_cell_mas = beam_fwhm / 6.0  

            original_size = image_data.shape[0]
            effective_cell = real_cell_mas * (original_size / img_size)
            beam_map = make_beam_map(beam_fwhm, effective_cell, img_size)

            fov_arcsec = effective_cell * img_size / 1000.0  
            beam_arcsec = beam_fwhm / 1000.0            
            scale_info = float(np.clip(beam_arcsec / (fov_arcsec + 1e-6), 0, 1))

            inclination = float(row_data["incl_deg"])
            pa_degrees = float(row_data["pa_deg"])
            labels = encode_labels(inclination, pa_degrees)

            self.samples.append((normalized_img, beam_map, labels, scale_info, effective_cell, fov_arcsec))
            success_count += 1

        print(f"  [FITSDataset] Loaded: {success_count}  Errors: {error_count}")
        print(f"  [FITSDataset] With augmentation x{augmentation_factor} -> {success_count * augmentation_factor} samples")

    def __len__(self):
        return len(self.samples) * self.augmentation_factor

    def __getitem__(self, idx):
        base_idx = idx % len(self.samples)
        img, beam, labels, scale_info, effective_cell, fov_arcsec = self.samples[base_idx]
        
        img = img.copy()
        labels = labels.copy()
        pa_degrees = float(np.degrees(np.arctan2(labels[1], labels[2])) / 2.0) % 180.0

        if self.rng.rand() < 0.5:
            img = np.fliplr(img).copy()
            pa_degrees = (180.0 - pa_degrees) % 180.0

        if self.rng.rand() < 0.5:
            img = np.flipud(img).copy()
            pa_degrees = (180.0 - pa_degrees) % 180.0

        if self.rng.rand() < 0.5:
            img = np.rot90(img).copy()
            pa_degrees = (pa_degrees + 90.0) % 180.0

        pa_radians = np.radians(pa_degrees)
        labels[1] = float(np.sin(2.0 * pa_radians))
        labels[2] = float(np.cos(2.0 * pa_radians))

        center_y, center_x = self.img_size // 2, self.img_size // 2
        y_grid, x_grid = np.ogrid[:self.img_size, :self.img_size]
        radii = np.sqrt((y_grid - center_y)**2 + (x_grid - center_x)**2)
        border_mask = radii > 0.80 * min(center_y, center_x)
        
        rms_noise = float(np.std(img[border_mask])) if np.any(border_mask) else 0.01
        noise_amplitude = self.rng.uniform(0.05, 0.15) * rms_noise
        
        img = img + self.rng.normal(0, noise_amplitude, img.shape).astype(np.float32)
        img = np.clip(img, 0, 1)

        scale_map = np.full((self.img_size, self.img_size), scale_info, dtype=np.float32)
        tensor_data = np.stack([img, beam, scale_map], axis=0)  
        
        return torch.tensor(tensor_data), torch.tensor(labels)

class SyntheticDataset(Dataset):
    def __init__(self, num_samples=SYNTHETIC_SAMPLES_COUNT, img_size=IMG_SIZE, seed=42):
        self.num_samples = num_samples
        self.img_size = img_size
        self.rng = np.random.RandomState(seed)
        
        print(f"  [SyntheticDataset] Generating {num_samples} samples ...")
        self.images, self.labels = self._generate()
        print(f"  [SyntheticDataset] Generation complete.")

    @staticmethod
    def _get_beam_kernel(beam_major, beam_minor, bpa_radians, size=21):
        x_coords = np.arange(-size, size + 1)
        x_grid, y_grid = np.meshgrid(x_coords, x_coords)
        
        x_rotated = x_grid * np.cos(bpa_radians) + y_grid * np.sin(bpa_radians)
        y_rotated = -x_grid * np.sin(bpa_radians) + y_grid * np.cos(bpa_radians)
        
        kernel = np.exp(-(x_rotated**2 / (2 * beam_major**2 + 1e-8) + y_rotated**2 / (2 * beam_minor**2 + 1e-8)))
        kernel = np.maximum(kernel, 0)
        kernel_sum = kernel.sum()
        
        return kernel / kernel_sum if kernel_sum > 0 else kernel

    def _generate(self):
        images = np.zeros((self.num_samples, 3, self.img_size, self.img_size), dtype=np.float32)
        labels = np.zeros((self.num_samples, 5), dtype=np.float32)
        
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
            
            disk_image = np.zeros_like(radii)
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
            
            sigma = (safe_radii / critical_radius)**(-gamma) * np.exp(-(safe_radii / critical_radius)**(2.0 - gamma))
            sigma = np.clip(sigma / (sigma.max() + 1e-10), 0, 1)

            t_zero = self.rng.uniform(40, 160)
            q_factor = self.rng.uniform(0.35, 0.55)
            tau = self.rng.uniform(1.5, 10.0)
            radial_temp = np.clip(t_zero * (safe_radii / max(rout_val * 0.05, 0.001))**(-q_factor), 5, 2000)
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
                disk_image *= 1.0 - gap_depth * np.exp(-0.5 * ((safe_radii - gap_radius) / (gap_width + 1e-5))**2)
                
                if self.rng.rand() < 0.80:
                    ring_radius = gap_radius + gap_width * self.rng.uniform(0.8, 2.5)
                    if ring_radius < rout_val * 0.95:
                        ring_width = gap_width * self.rng.uniform(0.5, 1.5)
                        ring_amplitude = self.rng.uniform(0.08, 0.40) * (np.max(disk_image) + 1e-15)
                        disk_image += ring_amplitude * np.exp(-0.5 * ((safe_radii - ring_radius) / (ring_width + 1e-5))**2)

            exponent = self.rng.uniform(1.5, 3.5)
            disk_image *= np.exp(-(safe_radii / (rout_val + 1e-5))**exponent)
            disk_image = np.maximum(disk_image, 0)

            beam_major = self.rng.uniform(0.3, 3.5)
            beam_minor = beam_major * self.rng.uniform(0.4, 0.95)
            beam_pa = self.rng.uniform(0, np.pi)
            target_snr = self.rng.uniform(5, 200)
            beam_kernel = self._get_beam_kernel(beam_major, beam_minor, beam_pa)

            blurred_image = convolve2d(disk_image.astype(np.float64), beam_kernel.astype(np.float64), mode='same')
            peak_flux = max(np.max(blurred_image), 1e-12)
            rms_noise = peak_flux / (target_snr + 1e-8)

            white_noise = self.rng.normal(0, 1, disk_image.shape)
            structured_noise = convolve2d(white_noise, beam_kernel, mode='same')
            structured_noise *= rms_noise / (np.std(structured_noise) + 1e-10)

            if self.rng.rand() < 0.50:
                low_freq_noise = gaussian_filter(self.rng.normal(0, 1, disk_image.shape), sigma=self.rng.uniform(4, 16))
                low_freq_noise *= self.rng.uniform(0.05, 0.20) * rms_noise / (np.std(low_freq_noise) + 1e-10)
                structured_noise = structured_noise + low_freq_noise

            final_image = blurred_image + structured_noise
            percentile_1 = np.percentile(final_image, 1)
            percentile_99 = np.percentile(final_image, 99.9)
            normalized_img = np.clip((final_image - percentile_1) / (percentile_99 - percentile_1 + 1e-8), 0, 1).astype(np.float32)

            if self.rng.rand() < 0.5:
                normalized_img = np.fliplr(normalized_img).copy()
                pa_degrees = (180.0 - pa_degrees) % 180.0
                dx = -dx
            if self.rng.rand() < 0.5:
                normalized_img = np.flipud(normalized_img).copy()
                pa_degrees = (180.0 - pa_degrees) % 180.0
                dy = -dy

            beam_fwhm_pixels = beam_major * 2.355
            center_y, center_x = self.img_size // 2, self.img_size // 2
            y_grid, x_grid = np.ogrid[:self.img_size, :self.img_size]
            gaussian_map = np.exp(-((x_grid - center_x)**2 + (y_grid - center_y)**2) / (2 * (beam_fwhm_pixels / 2.355)**2))
            beam_map = (gaussian_map / (gaussian_map.max() + 1e-10)).astype(np.float32)

            images[i, 0] = normalized_img
            images[i, 1] = beam_map

            beam_fwhm_arcsec = beam_major * 2.355 * arcsec_per_unit / (self.img_size / 2)
            scale_val = float(np.clip(beam_fwhm_arcsec / (crop_arcsec + 1e-6), 0, 1))
            images[i, 2] = scale_val 

            labels[i] = encode_labels(inclination, pa_degrees, dx=dx, dy=dy)

            if (i + 1) % 5000 == 0:
                print(f"    {i+1}/{self.num_samples}")

        return torch.tensor(images), torch.tensor(labels)

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
    lambda_val = float(np.random.beta(alpha, alpha))
    lambda_val = max(lambda_val, 1 - lambda_val)
    indices = torch.randperm(inputs.size(0), device=inputs.device)
    
    mixed_inputs = lambda_val * inputs + (1 - lambda_val) * inputs[indices]
    mixed_targets = lambda_val * targets + (1 - lambda_val) * targets[indices]
    
    return mixed_inputs, mixed_targets

def main():
    seed_val = 42
    torch.manual_seed(seed_val)
    np.random.seed(seed_val)

    computation_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[INFO] Device: {computation_device}")
    print(f"[INFO] IMG_SIZE={IMG_SIZE}px  |  Epochs={EPOCHS}  |  Batch={BATCH_SIZE}")

    print("\n[INFO] Loading real FITS dataset ...")
    fits_dataset = FITSDataset(simulations_dir=SIMULATIONS_DIR, catalog=CATALOG_FILE, augmentation_factor=REAL_AUGMENTATION_FACTOR, img_size=IMG_SIZE)

    print("\n[INFO] Generating synthetic dataset ...")
    synthetic_dataset = SyntheticDataset(num_samples=SYNTHETIC_SAMPLES_COUNT, img_size=IMG_SIZE, seed=seed_val)

    complete_dataset = ConcatDataset([fits_dataset, synthetic_dataset])
    total_samples = len(complete_dataset)
    val_samples = max(int(total_samples * 0.10), len(fits_dataset) // 5)
    train_samples = total_samples - val_samples

    print(f"\n[INFO] Total Dataset: {total_samples}")
    print(f"       Real FITS (augmented): {len(fits_dataset)}")
    print(f"       Synthetic:             {len(synthetic_dataset)}")
    print(f"       Train: {train_samples}  |  Validation: {val_samples}")

    train_subset, val_subset = random_split(complete_dataset, [train_samples, val_samples], generator=torch.Generator().manual_seed(seed_val))
    
    train_dataloader = DataLoader(train_subset, batch_size=BATCH_SIZE, shuffle=True, num_workers=0, pin_memory=True)
    val_dataloader = DataLoader(val_subset, batch_size=BATCH_SIZE, shuffle=False, num_workers=0, pin_memory=True)

    print("\n[INFO] Initializing DiskNet ...")
    neural_model = DiskNet(num_outputs=NUM_OUTPUTS).to(computation_device)
    param_count = sum(p.numel() for p in neural_model.parameters() if p.requires_grad)
    print(f"       Parameters: {param_count/1e6:.2f}M")

    network_optimizer = optim.AdamW(neural_model.parameters(), lr=LEARNING_RATE, weight_decay=1e-3)

    def learning_rate_schedule(epoch):
        warmup_epochs = 5
        if epoch < warmup_epochs:
            return (epoch + 1) / warmup_epochs
        progress = (epoch - warmup_epochs) / max(EPOCHS - warmup_epochs, 1)
        return 0.10 + 0.90 * 0.5 * (1 + np.cos(np.pi * progress))

    lr_scheduler = optim.lr_scheduler.LambdaLR(network_optimizer, learning_rate_schedule)
    best_val_loss = float("inf")

    print(f"\n[INFO] Training for {EPOCHS} epochs ...\n")
    print(f"{'Epoch':>6} | {'Train':>8} | {'Val':>8} | {'MAE_i':>7} | {'MAE_PA':>7} | LR")
    print("-" * 58)

    for epoch in range(1, EPOCHS + 1):
        neural_model.train()
        epoch_train_loss = 0.0
        
        for batch_inputs, batch_targets in train_dataloader:
            batch_inputs = batch_inputs.to(computation_device)
            batch_targets = batch_targets.to(computation_device)
            
            if np.random.rand() < 0.50:
                batch_inputs, batch_targets = mixup_batch(batch_inputs, batch_targets)
                
            network_optimizer.zero_grad()
            predictions = neural_model(batch_inputs)
            loss_val = custom_loss(predictions, batch_targets)
            loss_val.backward()
            nn.utils.clip_grad_norm_(neural_model.parameters(), 2.0)
            network_optimizer.step()
            epoch_train_loss += loss_val.item()

        neural_model.eval()
        epoch_val_loss = 0.0
        error_inclination = []
        error_pa = []

        with torch.no_grad():
            for batch_inputs, batch_targets in val_dataloader:
                batch_inputs = batch_inputs.to(computation_device)
                batch_targets = batch_targets.to(computation_device)
                
                predictions = neural_model(batch_inputs)
                epoch_val_loss += custom_loss(predictions, batch_targets).item()

                pred_incl = predictions[:, 0].cpu().numpy() * 90.0
                true_incl = batch_targets[:, 0].cpu().numpy() * 90.0
                
                pred_pa_deg = (np.degrees(np.arctan2(predictions[:, 1].cpu().numpy(), predictions[:, 2].cpu().numpy())) / 2.0) % 180.0
                true_pa_deg = (np.degrees(np.arctan2(batch_targets[:, 1].cpu().numpy(), batch_targets[:, 2].cpu().numpy())) / 2.0) % 180.0

                error_inclination.extend(np.abs(pred_incl - true_incl).tolist())
                pa_diff = np.abs(pred_pa_deg - true_pa_deg)
                error_pa.extend(np.minimum(pa_diff, 180.0 - pa_diff).tolist())

        avg_train_loss = epoch_train_loss / len(train_dataloader)
        avg_val_loss = epoch_val_loss / len(val_dataloader)
        mean_err_incl = np.mean(error_inclination)
        mean_err_pa = np.mean(error_pa)
        current_lr = network_optimizer.param_groups[0]["lr"]
        
        lr_scheduler.step()

        save_marker = " <-" if avg_val_loss < best_val_loss else ""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {epoch:3d}/{EPOCHS} | {avg_train_loss:.4f}   | {avg_val_loss:.4f}   | {mean_err_incl:5.1f}deg  | {mean_err_pa:5.1f}deg  | {current_lr:.2e}{save_marker}")

        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            torch.save({
                "epoch": epoch,
                "model_state": neural_model.state_dict(),
                "val_loss": best_val_loss,
                "img_size": IMG_SIZE,
                "n_out": NUM_OUTPUTS,
                "outputs": ["incl/90", "sin2PA", "cos2PA", "dx/0.14", "dy/0.14"],
            }, MODEL_SAVE_PATH)

    print(f"\n[DONE] Best model saved to -> '{MODEL_SAVE_PATH}'  (val={best_val_loss:.5f})")
    print(f"[INFO] Outputs: inclination, PA")
    print(f"[INFO] For inference: decode_labels(model(tensor_3x{IMG_SIZE}x{IMG_SIZE})[0])")

if __name__ == "__main__":
    main()