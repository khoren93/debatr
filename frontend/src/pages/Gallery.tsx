import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AudioLines, Play, Trophy, X } from 'lucide-react';
import { getErrorMessage } from '../api/client';
import { listGallery } from '../api/gallery';
import { GALLERY_CATEGORIES, type GalleryCategory, type GalleryItem, type GalleryPeriod, type GallerySort } from '../api/types';
import { Page, PageTitle } from '../components/layout/AppShell';
import { CardStats, DebateCard, DebateCover, PremiumVoicesBadge, VersionsBadge } from '../components/cards';
import { Avatar, Button, Chip, EmptyState, ErrorBox, LinkButton, ModelIcon, PageLoader, Segmented } from '../components/ui';
import { shortModelName } from '../lib/format';

type CategoryFilter = 'all' | GalleryCategory;

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const CATEGORY_OPTIONS: { value: CategoryFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  ...GALLERY_CATEGORIES.map((c) => ({ value: c, label: capitalize(c) })),
];

const SORT_OPTIONS: { value: GallerySort; label: string }[] = [
  { value: 'trending', label: 'Trending' },
  { value: 'new', label: 'New' },
  { value: 'top', label: 'Top' },
];

const PERIOD_OPTIONS: { value: GalleryPeriod; label: string }[] = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
  { value: 'all', label: 'All time' },
];

const oneOf = <T extends string>(value: string | null, options: { value: T }[], fallback: T): T => options.find((o) => o.value === value)?.value ?? fallback;

/**
 * Public gallery: one card per topic, whose cover is the version that earned it its place (the
 * most trending, newest or most liked one matching the filters). Sort, period and the model /
 * voice filters live in the URL (`?sort=top&period=week&model=…&voices=premium`).
 */
const Gallery = () => {
  const [params, setParams] = useSearchParams();
  const sort = oneOf(params.get('sort'), SORT_OPTIONS, 'trending');
  const period = oneOf(params.get('period'), PERIOD_OPTIONS, 'all');
  const model = params.get('model')?.trim() || null;
  const premium = params.get('voices') === 'premium';
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; items: GalleryItem[] } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);

  const setParam = (name: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value === null) next.delete(name);
        else next.set(name, value);
        return next;
      },
      { replace: true },
    );

  // One key per (filters, retry) so responses for a stale request are ignored.
  const key = `${category}|${sort}|${period}|${model ?? ''}|${premium}#${attempt}`;

  useEffect(() => {
    let cancelled = false;
    listGallery({
      category: category === 'all' ? undefined : category,
      sort,
      period: sort === 'top' ? period : undefined,
      model: model ?? undefined,
      premium_voices: premium || undefined,
      group: 'motion',
    })
      .then((res) => {
        if (!cancelled) setResult({ key, items: res.items });
      })
      .catch((err: unknown) => {
        if (!cancelled) setFailure({ key, message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [category, sort, period, model, premium, key]);

  const items = result?.key === key ? result.items : null;
  const error = failure?.key === key ? failure.message : null;
  const loading = items === null && error === null;
  // While a new category loads keep the previous grid on screen, dimmed.
  const shown = items ?? (loading ? (result?.items ?? null) : null);

  const renderBody = () => {
    if (error !== null) {
      return (
        <div className="mt-6 flex flex-col items-start gap-3">
          <ErrorBox className="w-full">Could not load the gallery: {error}</ErrorBox>
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        </div>
      );
    }
    if (shown === null) return <PageLoader label="Loading the gallery…" />;
    if (shown.length === 0) {
      if (premium) {
        return (
          <EmptyState
            className="mt-6"
            icon={<AudioLines className="size-5" />}
            title="No debates with premium voices here yet"
            text="Pick premium voices when you create a debate (or regenerate its audio) to be the first."
            action={
              <Button variant="secondary" onClick={() => setParam('voices', null)}>
                Show all voices
              </Button>
            }
          />
        );
      }
      if (model) {
        return (
          <EmptyState
            className="mt-6"
            icon={<Play className="size-5" />}
            title={`No public debates with ${shortModelName(model)} yet`}
            text="Run one with this model and publish it to be the first."
            action={
              <Button variant="secondary" onClick={() => setParam('model', null)}>
                Show all models
              </Button>
            }
          />
        );
      }
      if (sort === 'top' && period !== 'all') {
        return (
          <EmptyState
            className="mt-6"
            icon={<Play className="size-5" />}
            title="Nothing published in this period"
            action={
              <Button variant="secondary" onClick={() => setParam('period', 'all')}>
                Show all time
              </Button>
            }
          />
        );
      }
      return category === 'all' ? (
        <EmptyState
          className="mt-6"
          icon={<Play className="size-5" />}
          title="Nothing published yet"
          text="Public debates show up here once their authors share them. Be the first: run a debate and publish it."
          action={<LinkButton to="/create">Create a debate</LinkButton>}
        />
      ) : (
        <EmptyState
          className="mt-6"
          icon={<Play className="size-5" />}
          title={`No ${capitalize(category)} debates yet`}
          text="Nobody has published a debate in this category so far."
          action={
            <Button variant="secondary" onClick={() => setCategory('all')}>
              Show all categories
            </Button>
          }
        />
      );
    }
    return (
      <div className={`mt-[22px] grid grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))] gap-5 transition-opacity ${loading ? 'pointer-events-none opacity-50' : ''}`} aria-busy={loading}>
        {shown.map((item, i) => {
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
                  topLeft={<VersionsBadge motion={item.motion} participants={item.participants} />}
                  topRight={item.premium_voices ? <PremiumVoicesBadge /> : undefined}
                />
              }
              footerLeft={
                <>
                  <Avatar seed={author} size={20} />
                  <span className="truncate">{author}</span>
                </>
              }
              // No verdict on the cards: the audience votes blind on the debate page.
              footerRight={<CardStats likes={item.likes} views={item.views} durationMs={item.duration_ms} />}
            />
          );
        })}
      </div>
    );
  };

  return (
    <Page>
      <PageTitle
        kicker="Public"
        title="Gallery"
        right={
          <Link to="/leaderboard" className="inline-flex items-center gap-1.5 text-sm text-accent transition-colors hover:text-accent-hover">
            <Trophy className="size-4" /> Model ranking →
          </Link>
        }
      />
      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <Segmented options={SORT_OPTIONS} value={sort} onChange={(v) => setParam('sort', v === 'trending' ? null : v)} size="sm" />
        {sort === 'top' && <Segmented options={PERIOD_OPTIONS} value={period} onChange={(v) => setParam('period', v === 'all' ? null : v)} size="sm" />}
        <Chip size="sm" active={premium} onClick={() => setParam('voices', premium ? null : 'premium')} title="Only debates voiced with premium (ElevenLabs) voices">
          <AudioLines className="size-3.5" /> Premium voices
        </Chip>
        {model && (
          <button
            type="button"
            onClick={() => setParam('model', null)}
            className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/15 cursor-pointer"
            title="Remove the model filter"
          >
            <ModelIcon modelId={model} size={14} /> With {shortModelName(model)} <X className="size-3.5" />
          </button>
        )}
      </div>
      {/* One swipeable row on phones (edge to edge), wrapped on wider screens. */}
      <div
        className="-mx-[clamp(18px,4vw,48px)] mt-3.5 flex gap-2 overflow-x-auto px-[clamp(18px,4vw,48px)] [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0 [&::-webkit-scrollbar]:hidden"
        role="tablist"
        aria-label="Categories"
      >
        {CATEGORY_OPTIONS.map((opt) => (
          <Chip key={opt.value} className="shrink-0" active={opt.value === category} onClick={() => setCategory(opt.value)}>
            {opt.label}
          </Chip>
        ))}
      </div>
      {renderBody()}
    </Page>
  );
};

export default Gallery;
