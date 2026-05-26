import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const [info, range] = await Promise.all([
      device.getDeviceInfo(),
      device.getWavelengthRange(),
    ]);
    return Response.json({
      serialNumber: info.serialNumber.trim(),
      wavelengthRange: range,
    });
  } catch (err) {
    return errorResponse(err);
  }
}
