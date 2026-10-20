import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Layers, Plus } from 'lucide-react';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { getMotion } from '../api/motions';
import type { MotionPage } from '../api/types';
import { Page, PageTitle } from '../components/layout/AppShell';
import { CardStats, CoverBadge, DebateCard, DebateCover } from '../components/cards';
import { Avatar, Button, EmptyState, ErrorBox, LinkButton, PageLoader } from '../components/ui';

/** Language of a version when the topic is debated in more than one. */
const LanguageBadge = ({ code }: { code: string }) => (
  <span className="inline-block rounded-md bg-black/55 px-2 py-[3px] font-mono text-[10px] uppercase tracking-[0.06em] text-text backdrop-blur-sm">{code}</span>
);

/** `/t/:slug`: one topic and every published version of it (other models, other languages). */
const Topic = () => {
  const { slug = '' } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [attempt, setAttempt] = useState(0);
  const key = `${slug}#${attempt}`;
  const [loaded, setLoaded] = useState<{ key: string; page: MotionPage } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string; missing: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMotion(slug)
      .then((page) => {
        if (cancelled) return;
        // A topic merged into another one answers with that one: show its own address.
        if (page.slug !== slug) navigate(`/t/${page.slug}`, { replace: true });
        else setLoaded({ key, page });
      })
      .catch((err: unknown) => {
        if (!cancelled) setFailure({ key, message: getErrorMessage(err), missing: getErrorStatus(err) === 404 });
      });
    return () => {
      cancelled = true;
    };
  }, [slug, key, navigate]);

  const page = loaded?.key === key ? loaded.page : null;
  const error = failure?.key === key ? failure : null;

  if (error?.missing) {
    return (
      <Page>
        <EmptyState className="mt-6" icon={<Layers className="size-5" />} title="Nothing published on this topic" text="Its debates are private or were taken down." action={<LinkButton to="/gallery">Browse the gallery</LinkButton>} />
      </Page>
    );
  }
  if (error) {
    return (
      <Page>
        <div className="mt-6 flex flex-col items-start gap-3">
          <ErrorBox className="w-full">Could not load the topic: {error.message}</ErrorBox>
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        </div>
      </Page>
    );
  }
  if (!page) {
    return (
      <Page>
        <PageLoader label="Loading the topic…" />
      </Page>
    );
  }

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
              to={`/d/${item.slug}`}
              title={item.topic || item.title || 'Untitled debate'}
              cover={
                <DebateCover
                  participants={item.participants}
                  topLeft={languages.size > 1 ? <LanguageBadge code={item.language_code} /> : undefined}
                  topRight={<CoverBadge format={item.format} premiumVoices={item.premium_voices} />}
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
