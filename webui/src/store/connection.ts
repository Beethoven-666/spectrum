/**
 * Client-side connection store. The server is the source of truth; this just
 * mirrors the latest snapshot for the ConnectionBar.
 */

'use client';

import { create } from 'zustand';

import type { ConnectionStatus } from '@/lib/device-manager';

interface ConnectionStore {
  status: ConnectionStatus;
  setStatus: (s: ConnectionStatus) => void;
}

const EMPTY: ConnectionStatus = {
  connected: false,
  mode: null,
  port: null,
  openedAt: null,
};

export const useConnectionStore = create<ConnectionStore>((set) => ({
  status: EMPTY,
  setStatus: (s) => set({ status: s }),
}));
