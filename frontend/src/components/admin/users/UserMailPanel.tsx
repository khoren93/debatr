import { useCallback } from 'react';
import { Link } from 'react-router';
import { listMail } from '../../../api/admin/mail';
import { ErrorBox, Spinner } from '../../ui';
import { MailRow } from '../mail/MailRow';
import { useLoad } from '../useLoad';
import { Panel } from './UserSections';

const SHOWN = 10;

/** The letters the site sent the account (confirmations, resets, tests), newest first. */
export const UserMailPanel = ({ userId }: { userId: string }) => {
  const load = useCallback(() => listMail({ user_id: userId, limit: SHOWN }), [userId]);
  const { data, error } = useLoad(load);
  return (
    <Panel
      title="Mail"
      aside={
        data && (
          <span className="flex items-center gap-3">
            {data.total} {data.total === 1 ? 'letter' : 'letters'}
            {data.total > 0 && (
              <Link to={`/admin/mail?user=${userId}`} className="font-semibold hover:text-text">
                All letters
              </Link>
            )}
          </span>
        )
      }
    >
      {error && <ErrorBox className="m-3">{error}</ErrorBox>}
      {!data && !error && (
        <div className="flex justify-center py-6">
          <Spinner className="size-5" />
        </div>
      )}
      {data && data.total === 0 && <p className="px-4 py-4 text-sm text-muted">No letter sent to this account (letters are kept since the Mail page exists).</p>}
      {data && data.rows.length > 0 && (
        <ul className="divide-y divide-line/70">
          {data.rows.map((letter) => (
            <MailRow key={letter.id} letter={letter} account={false} />
          ))}
        </ul>
      )}
    </Panel>
  );
};
