/**
 * Public entry point for `@h1/sdk`.
 *
 * Importers typically only need `Device` plus the enums and error classes:
 *
 * ```ts
 * import { Device, ExposureMode } from '@h1/sdk';
 * const dev = new Device('/dev/cu.usbserial-XXX');
 * await dev.setExposureMode(ExposureMode.Auto);
 * ```
 *
 * The mock is exported from a separate subpath (`@h1/sdk/mock`) so production
 * bundles don't pull it in.
 */

export { Device } from './device.js';
export type { SerialPortLike } from './device.js';

export {
  H1Error,
  ProtocolError,
  TimeoutError,
  DeviceError,
} from './errors.js';

export {
  ExposureMode,
  WorkingMode,
  CieMode,
  ExposureStatus,
  DeviceStatus,
} from './types.js';

export type {
  WavelengthRange,
  DeviceInfo,
  PhotometricParams,
  BlueHazardParams,
  NirParams,
  PlantParams,
  Tm30Params,
  SpectrumFrame,
  DeviceOptions,
} from './types.js';

// Re-export the protocol layer for advanced users / debugging.
export * as protocol from './protocol.js';
