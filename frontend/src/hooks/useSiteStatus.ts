import { useEffect, useState } from 'react';
import { getSiteStatus } from '../api/status';
import type { SiteStatus } from '../api/types';

const OPEN: SiteStatus = {
  registration_open: true,
  maintenance: false,
  maintenance_message: null,
  free_debates: { per_day: 0, max_rounds: 0, max_debaters: 0, lengths: [] },
};
// Shared by every component; asked again when older than this (an admin may flip a lever).
const FRESH_MS = 60_000;
let cached: { at: number; status: SiteStatus } | null = null;
let inflight: Promise<SiteStatus> | null = null;

const load = (): Promise<SiteStatus> => {
  inflight ??= getSiteStatus()
    .then((status) => {
      cached = { at: Date.now(), status };
      return status;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
};

/** Sign-ups and maintenance mode (levers of the admin console); open until it answers. */
export const useSiteStatus = () => {
  const [status, setStatus] = useState<SiteStatus>(cached?.status ?? OPEN);

  useEffect(() => {
    if (cached && Date.now() - cached.at < FRESH_MS) return;
    let cancelled = false;
    load()
      .then((value) => {
        if (!cancelled) setStatus(value);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
};
