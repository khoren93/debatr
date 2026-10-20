import { useSiteUrl } from '../hooks/useSiteUrl';
import { APP_NAME } from '../lib/brand';
import { ROBOTS, canonicalUrl, jsonLdText, ogLocale, type SeoData } from '../lib/seo';

/**
 * A page's head for search engines and link previews (lib/seo.ts builds the data). React 19
 * hoists `<title>`, `<meta>` and `<link>` into `<head>` from anywhere in the tree and swaps them on
 * client navigations; JSON-LD stays in the body, where search engines read it as well. Every
 * page renders exactly one `<Seo>` (the document has no title of its own).
 */
export function Seo({ title, description, path, robots, type = 'website', image, lang, publishedAt, modifiedAt, jsonLd }: SeoData) {
  const site = useSiteUrl();
  const url = path !== undefined ? canonicalUrl(site, path) : undefined;
  const imageUrl = image && (image.url.startsWith('/') ? canonicalUrl(site, image.url) : image.url);
  const locale = ogLocale(lang);
  return (
    <>
      <title>{title}</title>
      {description && <meta name="description" content={description} />}
      <meta name="robots" content={ROBOTS[robots]} />
      {url && (
        <>
          <link rel="canonical" href={url} />
          <meta property="og:site_name" content={APP_NAME} />
          <meta property="og:type" content={type} />
          <meta property="og:title" content={title} />
          {description && <meta property="og:description" content={description} />}
          <meta property="og:url" content={url} />
          {locale && <meta property="og:locale" content={locale} />}
          {type === 'article' && publishedAt && <meta property="article:published_time" content={publishedAt} />}
          {type === 'article' && modifiedAt && <meta property="article:modified_time" content={modifiedAt} />}
          {image && imageUrl && (
            <>
              <meta property="og:image" content={imageUrl} />
              <meta property="og:image:width" content={String(image.width)} />
              <meta property="og:image:height" content={String(image.height)} />
              <meta property="og:image:alt" content={image.alt} />
              {image.type && <meta property="og:image:type" content={image.type} />}
              <meta name="twitter:image" content={imageUrl} />
              <meta name="twitter:image:alt" content={image.alt} />
            </>
          )}
          {/* X reads the rest from Open Graph; its player card needs X's approval, so no. */}
          <meta name="twitter:card" content={image ? 'summary_large_image' : 'summary'} />
        </>
      )}
      {jsonLd?.(site).map((item, i) => (
        <script key={i} type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdText(item) }} />
      ))}
    </>
  );
}
