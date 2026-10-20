import { Link, useNavigation, useSearchParams } from 'react-router';
import { ArrowLeft, ArrowRight, AudioLines, MicVocal, Play, Trophy, X } from 'lucide-react';
import type { GalleryItem } from '../api/types';
import { Page, PageTitle } from '../components/layout/AppShell';
import { CardCover, CardStats, CoverBadge, DebateCard, VersionsBadge } from '../components/cards';
import { Avatar, Button, Chip, EmptyState, LinkButton, ModelIcon, Segmented } from '../components/ui';
import { shortModelName } from '../lib/format';
import { CATEGORY_OPTIONS, FORMAT_OPTIONS, GALLERY_PAGE_SIZE, PERIOD_OPTIONS, SORT_OPTIONS, galleryHref, type GalleryFilters } from '../lib/gallery';

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

interface Props {
  filters: GalleryFilters;
  items: GalleryItem[];
  /** Cards (topics) across every page. */
  total: number;
}

const PAGE_LINK = 'inline-flex items-center gap-1.5 rounded-full border border-line-2 bg-surface px-3.5 py-2 text-[13px] font-semibold transition-colors hover:border-line-3 hover:bg-surface-2';

/** Previous / next page as real links, so crawlers reach every card (`?page=N`). */
const Pager = ({ filters, total }: { filters: GalleryFilters; total: number }) => {
  const pages = Math.ceil(total / GALLERY_PAGE_SIZE);
  if (pages <= 1) return null;
  const { page } = filters;
  return (
    <nav className="mt-8 flex items-center justify-center gap-3" aria-label="Gallery pages">
      {page > 1 ? (
        <Link to={galleryHref({ ...filters, page: page - 1 })} rel="prev" className={PAGE_LINK}>
          <ArrowLeft className="size-4" /> Previous
        </Link>
      ) : (
        <span className={`${PAGE_LINK} pointer-events-none opacity-40`} aria-hidden>
          <ArrowLeft className="size-4" /> Previous
        </span>
      )}
      <span className="font-mono text-xs text-muted">
        {page} / {pages}
      </span>
      {page < pages ? (
        <Link to={galleryHref({ ...filters, page: page + 1 })} rel="next" className={PAGE_LINK}>
          Next <ArrowRight className="size-4" />
        </Link>
      ) : (
        <span className={`${PAGE_LINK} pointer-events-none opacity-40`} aria-hidden>
          Next <ArrowRight className="size-4" />
        </span>
      )}
    </nav>
  );
};

/**
 * Public gallery: one card per topic, whose cover is the version that earned it its place (the
 * most trending, newest or most liked one matching the filters). Every filter lives in the URL
 * (`?sort=top&period=week&format=rap_battle&category=tech&model=…&voices=premium&page=2`): changing
 * one is a navigation (back to the first page), and the route's loaders bring the cards
 * (lib/gallery.ts).
 */
const Gallery = ({ filters, items, total }: Props) => {
  const { sort, period, format, category, model, premium } = filters;
  const [, setParams] = useSearchParams();
  const navigation = useNavigation();
  // While other filters load keep this grid on screen, dimmed.
  const loading = navigation.state === 'loading' && navigation.location.pathname === '/gallery';

  const setParam = (name: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value === null) next.delete(name);
        else next.set(name, value);
        next.delete('page');
        return next;
      },
      { replace: true, preventScrollReset: true },
    );

  const renderBody = () => {
    if (items.length === 0) {
      if (format === 'rap_battle') {
        return (
          <EmptyState
            className="mt-6"
            icon={<MicVocal className="size-5" />}
            title="No rap battles here yet"
            text="Two models trade verses over one beat and the judge scores every round. Stage the first one."
            action={<LinkButton to="/create?format=rap_battle">Start a battle</LinkButton>}
          />
        );
      }
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
            <Button variant="secondary" onClick={() => setParam('category', null)}>
              Show all categories
            </Button>
          }
        />
      );
    }
    return (
      <div className={`mt-[22px] grid grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))] gap-5 transition-opacity ${loading ? 'pointer-events-none opacity-50' : ''}`} aria-busy={loading}>
        {items.map((item, i) => {
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
                  priority={i === 0}
                  topLeft={<VersionsBadge motion={item.motion} participants={item.participants} />}
                  // An AI cover shows its format itself.
                  topRight={<CoverBadge format={item.cover ? undefined : item.format} premiumVoices={item.premium_voices} />}
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
        <Segmented options={FORMAT_OPTIONS} value={format} onChange={(v) => setParam('format', v === 'all' ? null : v)} size="sm" />
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
          <Chip key={opt.value} className="shrink-0" active={opt.value === category} onClick={() => setParam('category', opt.value === 'all' ? null : opt.value)}>
            {opt.label}
          </Chip>
        ))}
      </div>
      {renderBody()}
      <Pager filters={filters} total={total} />
    </Page>
  );
};

export default Gallery;
