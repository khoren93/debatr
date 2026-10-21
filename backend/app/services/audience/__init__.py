"""Who visits the site: visits (sessions) and what happened in them, for the admin console's
Audience page.

The browser sends a presence beacon (`POST /api/presence`, frontend lib/presence.ts) when a page
is shown, while it stays in front (the time it was looked at) and when the visitor does something
that matters (plays a video, signs up, starts a debate: `collect.ACTIONS`). The server adds what
the browser does not say: the IP and its place (`geo`, a local DB-IP database, no outside
service), the device and browser (`agent`), the account when signed in, and where the visit came
from (the landing page's referrer and campaign, classified like the views of debates:
services/views.classify). Bots (by User-Agent, and browsers driven by automation, which send
nothing) are left out, and so are visits of console staff in the statistics.

IP and User-Agent are cleared after the `analytics_ip_days` lever (`jobs.maintenance_job`); the
`analytics_enabled` lever turns the beacon off (the site then sends nothing at all).
"""
