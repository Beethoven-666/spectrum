export interface AcquisitionHealth {
  ok: boolean;
  service: string;
  version: string;
  mock: boolean;
}

export interface AcquisitionDevices {
  h1: DeviceInfo;
  d455: DeviceInfo;
  main_rgb: DeviceInfo;
}

export interface DeviceInfo {
  status: string;
  name?: string;
  serial?: string | null;
  serial_number?: string | null;
  wavelength_range?: { start: number; end: number } | null;
  exposure_time_us?: number | null;
  exposure_mode?: string | null;
  max_exposure_time_us?: number | null;
  detail?: Record<string, unknown>;
}

export interface StorageStatus {
  data_dir: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  warn_free_bytes: number;
  stop_free_bytes: number;
  status: 'good' | 'warn' | 'bad';
}

export interface AcquisitionConfig {
  data_dir: string;
  mock: boolean;
  roi: RoiConfig;
  d455_profile: {
    color_width: number;
    color_height: number;
    color_fps: number;
    depth_width: number;
    depth_height: number;
    depth_fps: number;
  };
  disk: {
    warn_free_bytes: number;
    stop_free_bytes: number;
    allow_below_stop: boolean;
  };
  h1_auto_exposure: {
    mode: ExposureMode;
    max_attempts: number;
    under_multiplier: number;
    over_multiplier: number;
    min_exposure_us: number;
    max_exposure_us: number;
    initial_exposure_us: number;
  };
  quality: {
    min_depth_valid_ratio: number;
    recommended_distance_min_mm: number;
    recommended_distance_max_mm: number;
    warn_angle_deg: number;
    bad_angle_deg: number;
    max_imu_delta_deg: number;
  };
  h1_port: string;
  calibration_path: string | null;
}

export interface RoiConfig {
  x: number;
  y: number;
  width: number;
  height: number;
  source: string;
}

export type ExposureMode = 'conservative' | 'strict' | 'multi_exposure';

export interface SaveConfigResponse {
  ok: boolean;
  config: AcquisitionConfig;
  restart_required: boolean;
}

export interface CalibrationStatus {
  status: 'uncalibrated' | 'configured' | 'missing';
  version: string | null;
  path: string | null;
}

export interface CalibrationSaveResponse {
  status: 'saved';
  version: string;
  path: string;
}

export interface AcquisitionSample {
  id: string;
  created_at: string;
  path: string;
  schema_version: string;
  quality_status: 'good' | 'warn' | 'bad';
  distance_mm: number | null;
  angle_deg: number | null;
  h1_exposure_status: string | null;
  d455_serial: string | null;
  h1_serial: string | null;
  main_rgb_status: string | null;
  calibration_version: string | null;
  config_profile: string | null;
  size_bytes: number;
  warnings: string[];
}

export interface SamplesResponse {
  samples: AcquisitionSample[];
}

export interface SampleDetailResponse {
  index: AcquisitionSample;
  metadata: Record<string, unknown>;
  quality: Record<string, unknown>;
}

export interface SampleSpectrum {
  status?: Record<string, unknown>;
  selected_attempt?: Record<string, unknown>;
  wavelengths?: number[];
  raw_spectrum?: number[];
  actual_spectrum?: number[];
  photometric?: Record<string, unknown>;
  plant?: Record<string, unknown>;
  spectrum_coefficient?: Record<string, unknown>;
}

export interface CaptureResponse {
  sample_id: string;
  sample_path: string;
  quality_status: 'good' | 'warn' | 'bad';
  warnings: string[];
  metadata?: Record<string, unknown>;
}

export interface ExportResponse {
  archive: string;
  filename: string;
}

export interface CaptureStatePayload {
  state: string;
  sample_id?: string | null;
  error?: string | null;
}

export function acquisitionPath(path: string): string {
  const normalized = path.startsWith('/') ? path.slice(1) : path;
  return `/api/acquisition/${normalized}`;
}
