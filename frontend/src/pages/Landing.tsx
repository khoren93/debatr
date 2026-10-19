import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listGallery } from '../api/gallery';
import type { GalleryItem, Participant } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { CardStats, DebateCard, DebateCover, PremiumVoicesBadge, VersionsBadge } from '../components/cards';
import { Avatar, Bars, LinkButton, LogoMark } from '../components/ui';
import { APP_DESCRIPTION, APP_NAME } from '../lib/brand';

const FACTS = ['60+ models', 'Neural voices', '16:9 + 9:16', 'No install'];

const STEPS = [
  {
    title: 'Pick a question',
    text: 'Type your own or grab one from the library. Add an angle if you want the models to dig somewhere specific.',
  },
  {
    title: 'Cast the speakers',
    text: 'A moderator, a pro and a con. Any of 60+ models, each with its own neural voice and persona.',
  },
  {
    title: 'Render & publish',
    text: 'Get the full 16:9 episode and a 9:16 Short with hook and captions — rendered right in your browser.',
  },
];

const HERO_GLOW =
  'radial-gradient(60% 60% at 70% 30%, rgba(217,255,61,0.14), transparent 60%), radial-gradient(40% 50% at 20% 60%, rgba(108,156,255,0.16), transparent 60%)';

/** Lineup and question of the hero's poster (a static mock, no data involved). */
const HERO_LINEUP: Participant[] = [
  { name: 'Claude Opus 5.5', role: 'debater', model: 'anthropic/claude-opus-5.5', voice_name: null, avatar: null },
  { name: 'GPT-6.1 Sol', role: 'debater', model: 'openai/gpt-6.1-sol', voice_name: null, avatar: null },
];
const HERO_TOPIC = 'Will smart contracts replace banks?';

/** The long video's first frame (brand bar, face-off, question), sized in `cqw` of the poster. */
const HeroPlayer = () => (
  <div className="group relative animate-rise" style={{ animationDuration: '0.7s', animationDelay: '0.1s' }}>
    <div className="overflow-hidden rounded-panel border border-line-2 shadow-[0_40px_80px_-30px_rgba(0,0,0,0.8)]">
      <DebateCover
        layout="poster"
        participants={HERO_LINEUP}
        topLeft={
          <span className="flex items-center gap-[1.3cqw]">
            <span className="block size-[max(18px,4.4cqw)] [&>svg]:size-full">
              <LogoMark />
            </span>
            <span className="font-display text-[max(10px,2.2cqw)] font-bold tracking-[-0.025em]">{APP_NAME}</span>
          </span>
        }
        topRight={<span className="flex h-[max(18px,4.4cqw)] items-center rounded-full border-2 border-white/14 bg-ink/70 px-[1.5cqw] font-mono text-[max(8px,1.25cqw)] tracking-[0.1em] text-accent">AI DEBATE</span>}
      >
        {/* Kept above the floating render card. */}
        <div className="absolute inset-x-[7%] bottom-[max(46px,8cqw)] text-center font-display text-[4cqw] font-extrabold leading-[1.06] tracking-[-0.03em] text-balance">{HERO_TOPIC}</div>
      </DebateCover>
    </div>
    <div className="absolute -bottom-[22px] right-0 flex items-center gap-3 rounded-[14px] border border-line-2 bg-surface-2 px-3.5 py-3 shadow-[0_20px_40px_-20px_rgba(0,0,0,0.8)] sm:-right-2">
      <Bars />
      <div>
        <div className="text-xs font-semibold">Rendering Short</div>
        <div className="font-mono text-[11px] text-muted">1890 / 1890 frames</div>
      </div>
    </div>
  </div>
);

/** Debates in the "Trending in the gallery" row. */
const FEATURED = 3;

const Landing = () => {
  const { user } = useAuth();
  const [featured, setFeatured] = useState<GalleryItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    // The landing is the first impression: debates with premium voices come first, the
    // general trending list only fills the free places.
    // One card per topic in both lists; a topic in both shows its premium version.
    Promise.all([listGallery({ limit: FEATURED, sort: 'trending', premium_voices: true, group: 'motion' }), listGallery({ limit: FEATURED, sort: 'trending', group: 'motion' })])
      .then(([premium, all]) => {
        if (cancelled) return;
        const topicOf = (item: GalleryItem) => item.motion?.slug ?? item.id;
        const topics = new Set(premium.items.map(topicOf));
        setFeatured([...premium.items, ...all.items.filter((item) => !topics.has(topicOf(item)))].slice(0, FEATURED));
      })
      .catch(() => {
        // The "Trending in the gallery" section is optional: it stays hidden when the gallery is unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Page className="relative" fit>
      {/* As wide as the viewport, so it does not stop at the capped content width (the shell's
          <main> clips it at the sidebar). */}
      <div className="pointer-events-none absolute -top-60 left-1/2 h-[1040px] w-screen -translate-x-1/2" style={{ background: HERO_GLOW }} aria-hidden="true" />

      {/* Hero */}
      <div className="relative grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] items-center gap-[clamp(28px,4vw,56px)]">
        <div className="animate-rise" style={{ animationDuration: '0.6s' }}>
          <div className="inline-flex items-center gap-2 rounded-full border border-accent/35 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] text-accent">
            <span className="size-1.5 rounded-full bg-accent animate-pulse-dot" />
            AI DEBATE STUDIO
          </div>
          <h1 className="mt-4 font-display text-[clamp(38px,3.85vw,62px)] font-extrabold leading-[1.02] tracking-[-0.035em] text-balance">
            Two AIs. One topic.
            <br />
            <span className="text-accent">A video in minutes.</span>
          </h1>
          <p className="mt-4 max-w-[540px] text-[clamp(15px,1.15vw,18px)] leading-[1.5] text-text-3 text-pretty">{APP_DESCRIPTION}</p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <LinkButton to="/create" size="lg">
              Create a debate
            </LinkButton>
            <LinkButton to="/gallery" variant="secondary" size="lg">
              Watch examples
            </LinkButton>
            {user && (
              <Link to="/library" className="px-2 text-sm text-muted transition-colors hover:text-text">
                Go to library →
              </Link>
            )}
          </div>
          <div className="mt-5 flex flex-wrap gap-[22px] font-mono text-xs text-muted">
            {FACTS.map((fact) => (
              <span key={fact}>{fact}</span>
            ))}
          </div>
        </div>
        <HeroPlayer />
      </div>

      {/* How it works */}
      <div className="relative mt-[clamp(32px,3.5vw,48px)] grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-3.5">
        {STEPS.map((step, i) => (
          <div key={step.title} className="rounded-card border border-line bg-surface px-5 py-4">
            <div className="flex items-baseline gap-3">
              <span className="font-mono text-xs text-accent">0{i + 1}</span>
              <span className="font-display text-[19px] font-bold tracking-[-0.02em]">{step.title}</span>
            </div>
            <div className="mt-1.5 text-sm leading-[1.5] text-muted text-pretty">{step.text}</div>
          </div>
        ))}
      </div>

      {/* Featured public debates */}
      {featured.length > 0 && (
        <div className="relative mt-[clamp(32px,3.5vw,48px)]">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 className="font-display text-[clamp(22px,2.2vw,30px)] font-bold tracking-[-0.03em]">Trending in the gallery</h2>
            <Link to="/gallery" className="text-sm text-accent transition-colors hover:text-accent-hover">
              Browse gallery →
            </Link>
          </div>
          <div className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))] gap-5 xl:grid-cols-3">
            {featured.map((item, i) => (
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
                    <Avatar seed={item.author_name?.trim() || 'Anonymous'} size={20} />
                    <span className="truncate">{item.author_name?.trim() || 'Anonymous'}</span>
                  </>
                }
                footerRight={<CardStats likes={item.likes} views={item.views} durationMs={item.duration_ms} />}
              />
            ))}
          </div>
        </div>
      )}
    </Page>
  );
};

export default Landing;
