import { OfficialMark, UserAvatar } from '../ui';

/** A card's author: avatar and name; the site's own account gets its logo and the official mark. */
export const CardAuthor = ({ name, official = false }: { name: string | null | undefined; official?: boolean }) => {
  const author = name?.trim() || 'Anonymous';
  return (
    <>
      <UserAvatar seed={author} official={official} size={20} />
      <span className="truncate">{author}</span>
      {official && <OfficialMark />}
    </>
  );
};
