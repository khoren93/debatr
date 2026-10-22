import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { Page, PageTitle } from '../components/layout/AppShell';
import { APP_NAME, APP_REPO_URL } from '../lib/brand';

const Block = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="mt-8">
    <h2 className="font-display text-lg font-bold tracking-tight">{title}</h2>
    <div className="mt-2 grid gap-3 text-sm leading-relaxed text-text-3">{children}</div>
  </section>
);

/** The privacy notice (`/privacy`). Keep it true to the code: backend services/audience
 *  (visits and their bot verdicts; the IP is cleared after the console's analytics_ip_days
 *  lever), accounts, keys. */
const Privacy = () => (
  <Page>
    <PageTitle kicker="Legal" title="Privacy" />
    <div className="max-w-2xl">
      <p className="mt-4 text-sm leading-relaxed text-text-3">What {APP_NAME} keeps, why, and for how long. We do not sell data and show no ads.</p>

      <Block title="Your account">
        <p>Your email, display name and a hash of your password; the debates you run, your credits and their history. Payments go through Stripe: we never see card numbers.</p>
        <p>Public debates show your display name. You can make a debate private again at any time.</p>
      </Block>

      <Block title="Visits">
        <p>
          To see how people find and use the site, we record the pages you open, how long they stay in front of you, a few actions (such as playing a video or starting a debate), the
          site you came from and the browser’s technical details: IP address, the approximate place it belongs to, device and browser type, screen size and language. A random
          identifier in your browser’s local storage tells repeat visits apart; clearing the site’s data resets it.
        </p>
        <p>
          To keep bots and automated browsers out of these numbers, the page also counts how much you used the mouse, touch screen, keyboard and scroll wheel (counts only: never
          what you typed or where you pointed), checks a few facts about the browser (such as whether it draws graphics on a GPU and which platform it runs on) and looks up the
          network operator of the IP address.
        </p>
        <p>This runs on our own servers: no third-party analytics or advertising trackers. IP addresses are deleted after 90 days.</p>
      </Block>

      <Block title="Keys and providers">
        <p>
          OpenRouter or ElevenLabs keys you enter in the browser stay in your browser and are sent only with the request that uses them; an OpenRouter key saved to your account is
          stored encrypted. Debate texts go to the AI models you pick (through OpenRouter) and, for audio, to the voice provider.
        </p>
      </Block>

      <Block title="Questions and deletion">
        <p>
          To get a copy of your data or have your account deleted, open an issue at{' '}
          <a href={APP_REPO_URL} className="text-accent hover:text-accent-hover" rel="noreferrer" target="_blank">
            github.com/khoren93/debatr
          </a>{' '}
          or write from your account’s email. <Link to="/" className="text-accent hover:text-accent-hover">Back to {APP_NAME}</Link>.
        </p>
      </Block>
    </div>
  </Page>
);

export default Privacy;
