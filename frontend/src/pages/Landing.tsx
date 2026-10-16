import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Heart } from 'lucide-react';
import { listGallery } from '../api/gallery';
import type { GalleryItem } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { DebateCard, DurationChip, VersusLine } from '../components/cards';
import { Bars, LinkButton } from '../components/ui';
import { APP_DESCRIPTION } from '../lib/brand';
import { formatCount } from '../lib/format';

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

/** Static mock of the 16:9 player from the design (no data involved). */
const HeroPlayer = () => (
  <div className="relative animate-rise" style={{ animationDuration: '0.7s', animationDelay: '0.1s' }}>
    <div className="relative aspect-video overflow-hidden rounded-panel border border-line-2 bg-surface shadow-[0_40px_80px_-30px_rgba(0,0,0,0.8)]">
      <div className="absolute inset-0 grid grid-cols-2">
        <div className="flex items-end p-[18px] pb-[92px]" style={{ background: 'linear-gradient(160deg,#1a2a55,#0f1730)' }}>
          <div>
            <div className="font-mono text-[10px] tracking-[0.1em] text-pro">PRO</div>
            <div className="text-[15px] font-bold">Claude Sonnet</div>
          </div>
        </div>
        <div className="flex items-end justify-end p-[18px] pb-[92px] text-right" style={{ background: 'linear-gradient(200deg,#4a1f1b,#2a1210)' }}>
          <div>
            <div className="font-mono text-[10px] tracking-[0.1em] text-con">CON</div>
            <div className="text-[15px] font-bold">GPT-4o</div>
          </div>
        </div>
      </div>
      <div className="absolute inset-y-0 left-1/2 w-px bg-white/15" />
      <div className="absolute inset-x-0 top-0 flex items-center justify-between px-[18px] py-3.5">
        <span className="font-mono text-[10px] tracking-[0.1em] text-host">ROUND 2 · REBUTTAL</span>
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-text">
          <span className="size-[7px] rounded-full bg-danger animate-pulse-dot" style={{ animationDuration: '1.2s' }} />
          REC
        </span>
      </div>
      <div className="absolute inset-x-0 bottom-0 flex justify-center px-[18px] pb-3.5">
        <div className="max-w-[78%] rounded-field bg-ink/80 px-4 py-2.5 text-center font-display text-[clamp(13px,1.3vw,17px)] font-bold leading-[1.3] backdrop-blur-lg">
          “Smart contracts automate <span className="text-accent">trust</span>. Banks can't compete with that.”
        </div>
      </div>
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

const Landing = () => {
  const { user } = useAuth();
  const [featured, setFeatured] = useState<GalleryItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    listGallery({ limit: 3, sort: 'trending' })
      .then((res) => {
        if (!cancelled) setFeatured(res.items);
      })
      .catch(() => {
        // The "Trending in the gallery" section is optional: it stays hidden when the gallery is unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Page className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-[-10%] top-[-20%] h-[70%]" style={{ background: HERO_GLOW }} aria-hidden="true" />

      {/* Hero */}
      <div className="relative grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] items-center gap-[clamp(28px,5vw,64px)] pt-[clamp(8px,2.5vw,44px)]">
        <div className="animate-rise" style={{ animationDuration: '0.6s' }}>
          <div className="inline-flex items-center gap-2 rounded-full border border-accent/35 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] text-accent">
            <span className="size-1.5 rounded-full bg-accent animate-pulse-dot" />
            AI DEBATE STUDIO
          </div>
          <h1 className="mt-[22px] font-display text-[clamp(40px,6.2vw,84px)] font-extrabold leading-[0.98] tracking-[-0.035em] text-balance">
            Two AIs.
            <br />
            One topic.
            <br />
            <span className="text-accent">A video in minutes.</span>
          </h1>
          <p className="mt-[22px] max-w-[520px] text-[clamp(16px,1.4vw,19px)] leading-[1.5] text-text-3 text-pretty">{APP_DESCRIPTION}</p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
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
          <div className="mt-[34px] flex flex-wrap gap-[22px] font-mono text-xs text-muted">
            {FACTS.map((fact) => (
              <span key={fact}>{fact}</span>
            ))}
          </div>
        </div>
        <HeroPlayer />
      </div>

      {/* How it works */}
      <div className="relative mt-[clamp(70px,9vw,120px)] grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-3.5">
        {STEPS.map((step, i) => (
          <div key={step.title} className="rounded-card border border-line bg-surface p-6">
            <div className="font-mono text-xs text-accent">0{i + 1}</div>
            <div className="mt-3.5 font-display text-[22px] font-bold tracking-[-0.02em]">{step.title}</div>
            <div className="mt-2 text-sm leading-[1.5] text-muted text-pretty">{step.text}</div>
          </div>
        ))}
      </div>

      {/* Featured public debates */}
      {featured.length > 0 && (
        <div className="relative mt-[clamp(60px,8vw,100px)]">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 className="font-display text-[clamp(26px,3vw,38px)] font-bold tracking-[-0.03em]">Trending in the gallery</h2>
            <Link to="/gallery" className="text-sm text-accent transition-colors hover:text-accent-hover">
              Browse gallery →
            </Link>
          </div>
          <div className="mt-[22px] grid grid-cols-[repeat(auto-fill,minmax(min(100%,280px),1fr))] gap-4">
            {featured.map((item, i) => (
              <DebateCard
                key={item.id}
                id={item.id}
                index={i}
                to={`/d/${item.slug}`}
                title={item.topic || item.title || 'Untitled debate'}
                topLeft={<VersusLine participants={item.participants} />}
                topRight={<DurationChip ms={item.duration_ms} />}
                footerLeft={<span>{formatCount(item.views)} views</span>}
                footerRight={
                  <span className="inline-flex items-center gap-1">
                    <Heart className="size-3" /> {formatCount(item.likes)}
                  </span>
                }
              />
            ))}
          </div>
        </div>
      )}
    </Page>
  );
};

export default Landing;
