import { Plus } from 'lucide-react';
import type { MotionPage } from '../api/types';
import { Page, PageTitle } from '../components/layout/AppShell';
import { CardCover, CardStats, CoverBadge, DebateCard } from '../components/cards';
import { Avatar, LinkButton } from '../components/ui';

/** Language of a version when the topic is debated in more than one. */
const LanguageBadge = ({ code }: { code: string }) => (
  <span className="inline-block rounded-md bg-black/55 px-2 py-[3px] font-mono text-[10px] uppercase tracking-[0.06em] text-text backdrop-blur-sm">{code}</span>
);

/** `/t/:slug`: one topic and every published version of it (other models, other languages);
 *  the route loads it (a merged topic redirects to the one it went into). */
const Topic = ({ page }: { page: MotionPage }) => {
  const languages = new Set(page.items.map((item) => item.language_code));
  // The remix starts from the most liked version (the list comes most liked first).
  const best = page.items[0];
  return (
    <Page>
      <PageTitle
        kicker={`Topic · ${page.versions} ${page.versions === 1 ? 'version' : 'versions'}`}
        title={<span className="text-balance">{page.title}</span>}
        right={
          best && (
            <LinkButton to={`/create?remix=${best.id}`} icon={<Plus className="size-4" />}>
              Add your version
            </LinkButton>
          )
        }
      />
      <p className="mt-3 max-w-[640px] text-sm leading-normal text-muted">The same question argued by different models{languages.size > 1 ? ' and in different languages' : ''}. Pick a version to watch, or run it with your own lineup.</p>
      <div className="mt-[22px] grid grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))] gap-5">
        {page.items.map((item, i) => {
          const author = item.author_name?.trim() || 'Anonymous';
          return (
            <DebateCard
              key={item.id}
              id={item.id}
              index={i}
              to={item.path || `/d/${item.slug}`}
              title={item.topic || item.title || 'Untitled debate'}
              cover={
                <CardCover
                  cover={item.cover}
                  participants={item.participants}
                  topLeft={languages.size > 1 ? <LanguageBadge code={item.language_code} /> : undefined}
                  topRight={<CoverBadge format={item.cover ? undefined : item.format} premiumVoices={item.premium_voices} />}
                />
              }
              footerLeft={
                <>
                  <Avatar seed={author} size={20} />
                  <span className="truncate">{author}</span>
                </>
              }
              footerRight={<CardStats likes={item.likes} views={item.views} durationMs={item.duration_ms} />}
            />
          );
        })}
      </div>
    </Page>
  );
};

export default Topic;
