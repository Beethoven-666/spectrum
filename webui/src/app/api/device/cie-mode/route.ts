import { CieMode } from '@h1/sdk';

import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const NUM_TO_NAME: Record<number, string> = {
  [CieMode.Cie1931_2]: 'cie1931_2',
  [CieMode.Cie1964_10]: 'cie1964_10',
  [CieMode.Cie2015_2]: 'cie2015_2',
  [CieMode.Cie2015_10]: 'cie2015_10',
};
const NAME_TO_NUM: Record<string, CieMode> = {
  cie1931_2: CieMode.Cie1931_2,
  cie1964_10: CieMode.Cie1964_10,
  cie2015_2: CieMode.Cie2015_2,
  cie2015_10: CieMode.Cie2015_10,
};

export async function GET(): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const mode = await device.getCieMode();
    return Response.json({ mode: NUM_TO_NAME[mode] ?? 'cie1931_2' });
  } catch (err) {
    return errorResponse(err);
  }
}

interface CieBody {
  mode: keyof typeof NAME_TO_NUM;
}

export async function PUT(request: Request): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const body = (await request.json()) as CieBody;
    const num = NAME_TO_NUM[body.mode];
    if (num === undefined) {
      return Response.json({ error: `unknown CIE mode "${body.mode}"` }, { status: 400 });
    }
    await device.setCieMode(num);
    const current = await device.getCieMode();
    return Response.json({ mode: NUM_TO_NAME[current] ?? 'cie1931_2' });
  } catch (err) {
    return errorResponse(err);
  }
}
