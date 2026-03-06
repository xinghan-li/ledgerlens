import Link from 'next/link'
import { notFound } from 'next/navigation'
import ReactMarkdown from 'react-markdown'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type Post = { slug: string; title: string; subtitle?: string; date: string; body: string }

async function getPost(slug: string): Promise<Post | null> {
  try {
    const res = await fetch(`${API_BASE}/api/blog/${encodeURIComponent(slug)}`, {
      next: { revalidate: 60 },
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export default async function CommunicationsPostPage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  const post = await getPost(slug)
  if (!post) notFound()

  return (
    <div className="min-h-full bg-theme-cream">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-16">
      <Link
        href="/communications"
        className="text-sm font-medium text-theme-mid hover:text-theme-dark mb-8 inline-block"
      >
        ← Communications
      </Link>
      <header className="mb-10">
        <h1 className="font-heading text-3xl sm:text-4xl font-bold text-theme-dark">
          {post.title}
        </h1>
        {post.subtitle && (
          <p className="text-theme-mid mt-1 text-lg">
            {post.subtitle}
          </p>
        )}
        {post.date && (
          <time
            dateTime={post.date}
            className="text-theme-mid mt-2 block"
          >
            {formatDate(post.date)}
          </time>
        )}
      </header>
      <div className="prose prose-theme max-w-none">
        <ReactMarkdown
          components={{
            h2: ({ children }) => (
              <h2 className="font-heading text-xl font-semibold mt-8 mb-3 text-theme-dark">
                {children}
              </h2>
            ),
            h3: ({ children }) => (
              <h3 className="font-heading text-lg font-semibold mt-6 mb-2 text-theme-dark">
                {children}
              </h3>
            ),
            p: ({ children }) => (
              <p className="text-theme-dark/90 mb-4 leading-relaxed">
                {children}
              </p>
            ),
            ul: ({ children }) => (
              <ul className="list-disc pl-6 mb-4 space-y-1 text-theme-dark/90">
                {children}
              </ul>
            ),
            strong: ({ children }) => (
              <strong className="font-semibold text-theme-dark">
                {children}
              </strong>
            ),
          }}
        >
          {post.body}
        </ReactMarkdown>
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
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}
