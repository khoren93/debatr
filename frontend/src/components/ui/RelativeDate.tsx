import { useHydrated } from '../../hooks/useHydrated';
import { formatAgo, formatDate, formatDateShort } from '../../lib/format';

/** "5 days ago" (the viewer's calendar days) with the local date and time on hover. The server
 *  knows neither the viewer's zone nor the moment of hydration: until then it is the UTC date. */
export const RelativeDate = ({ iso, className }: { iso: string; className?: string }) => {
  const hydrated = useHydrated();
  return (
    <time dateTime={iso} className={className} title={hydrated ? formatDate(iso) : undefined}>
      {hydrated ? formatAgo(iso) : formatDateShort(iso, 'UTC')}
    </time>
  );
};
