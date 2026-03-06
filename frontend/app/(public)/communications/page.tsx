import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type PostMeta = { slug: string; title: string; subtitle?: string; date: string; excerpt: string; type?: string }

async function getPosts(): Promise<PostMeta[]> {
  try {
    const res = await fetch(`${API_BASE}/api/blog`, { next: { revalidate: 60 } })
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}

type Tab = 'articles' | 'updates'

export default async function CommunicationsListPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>
}) {
  const params = await searchParams
  const tab: Tab =
    params.tab === 'updates' ? 'updates' : 'articles'

  const allPosts = await getPosts()
  const articles = allPosts.filter((p) => (p.type || 'article') === 'article')
  const updates = allPosts.filter((p) => p.type === 'update')
  const posts = tab === 'updates' ? updates : articles

  return (
    <div className="flex flex-col bg-theme-cream min-h-full">
      <section className="w-full bg-theme-cream">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12 sm:py-16 text-left">
          <h1 className="font-heading text-4xl sm:text-5xl font-bold mb-3 text-theme-dark">
            Communications
          </h1>
          <p className="text-lg sm:text-xl text-theme-dark/80">
            Updates, patch notes, and what we&apos;re building.
          </p>
          <nav
            className="mt-8 flex items-center justify-start gap-6 font-heading text-theme-dark"
            aria-label="Communications sections"
          >
            <Link
              href="/communications?tab=articles"
              className={`text-lg font-medium hover:underline underline-offset-4 decoration-2 decoration-theme-dark ${
                tab === 'articles' ? 'underline' : 'no-underline'
              }`}
            >
              Articles
            </Link>
            <span className="text-theme-mid font-normal" aria-hidden>
              /
            </span>
            <Link
              href="/communications?tab=updates"
              className={`text-lg font-medium hover:underline underline-offset-4 decoration-2 decoration-theme-dark ${
                tab === 'updates' ? 'underline' : 'no-underline'
              }`}
            >
              Updates
            </Link>
          </nav>
        </div>
      </section>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 pb-16 w-full flex-1 bg-theme-cream">
        <div className="space-y-10">
          {posts.length === 0 ? (
            <p className="text-theme-mid">
              {tab === 'updates'
                ? 'No updates yet.'
                : 'No articles yet.'}
            </p>
          ) : (
            posts.map((post) => (
              <article key={post.slug} className="group">
                <Link
                  href={`/communications/${post.slug}`}
                  className="block rounded-lg border border-theme-light-gray/60 bg-white p-6 shadow-sm transition hover:border-theme-mid/50 hover:shadow-md"
                >
                  <div className="flex justify-between items-start gap-4">
                    <div className="min-w-0">
                      <h2 className="font-heading text-xl font-semibold text-theme-dark group-hover:text-theme-orange transition-colors">
                        {post.title}
                      </h2>
                      {post.subtitle && (
                        <p className="text-sm text-theme-dark mt-0.5">
                          {post.subtitle}
                        </p>
                      )}
                    </div>
                    {post.date && (
                      <time
                        dateTime={post.date}
                        className="text-sm font-medium text-theme-dark shrink-0"
                      >
                        {formatDate(post.date)}
                      </time>
                    )}
                  </div>
                </Link>
              </article>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    if (Number.isNaN(d.getTime())) return dateStr
    return d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
    })
  } catch {
    return dateStr
  }
}
