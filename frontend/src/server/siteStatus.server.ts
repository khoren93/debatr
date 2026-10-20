import { serverApi } from '../api/server.server';
import type { SiteStatus } from '../api/types';

/** Site levers change rarely and are the same for everyone: one API call per 30 s per process. */
const FRESH_MS = 30_000;
let memo: { at: number; status: SiteStatus } | null = null;

export async function serverSiteStatus(request: Request): Promise<SiteStatus | null> {
  if (memo && Date.now() - memo.at < FRESH_MS) return memo.status;
  try {
    const status = await serverApi<SiteStatus>(request, '/status');
    memo = { at: Date.now(), status };
    return status;
  } catch (err) {
    if (request.signal.aborted) throw err;
    return memo?.status ?? null;
  }
}
