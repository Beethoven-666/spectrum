/**
 * Connection status derived from the acquisition service (H1 gateway mode).
 */

export type DeviceMode = 'gateway';

export interface ConnectionStatus {
  connected: boolean;
  mode: DeviceMode | null;
  port: string | null;
  openedAt: string | null;
  serialNumber?: string | null;
  status?: string;
}

export const GATEWAY_DISCONNECTED: ConnectionStatus = {
  connected: false,
  mode: 'gateway',
  port: null,
  openedAt: null,
  serialNumber: null,
  status: 'offline',
};
