import type { ReactNode } from 'react'

/** Spacious module shell — card with header band and padded body. */
export function ModuleCard({
  title,
  subtitle,
  children,
  action,
  footer,
  className = '',
}: {
  title: string
  subtitle?: string
  children: ReactNode
  action?: ReactNode
  footer?: ReactNode
  className?: string
}) {
  return (
    <section className={`module-card ${className}`.trim()}>
      <header className="module-card-header">
        <div className="min-w-0 flex-1">
          <h2 className="module-card-title">{title}</h2>
          {subtitle ? <p className="module-card-subtitle">{subtitle}</p> : null}
        </div>
        {action ? <div className="module-card-action shrink-0">{action}</div> : null}
      </header>
      <div className="module-card-body">{children}</div>
      {footer ? <footer className="module-card-footer">{footer}</footer> : null}
    </section>
  )
}

export function StatTile({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: string | number
  hint?: string
  tone?: 'neutral' | 'lime' | 'magenta' | 'cyan' | 'amber'
}) {
  return (
    <div className={`stat-tile stat-tile-${tone}`}>
      <div className="stat-tile-label">{label}</div>
      <div className="stat-tile-value">{value}</div>
      {hint ? <div className="stat-tile-hint">{hint}</div> : null}
    </div>
  )
}

export function PageHeader({
  kicker,
  title,
  highlight,
  lede,
  actions,
}: {
  kicker?: string
  title: string
  highlight?: string
  lede?: string
  actions?: ReactNode
}) {
  return (
    <header className="page-header mb-8 lg:mb-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          {kicker ? <p className="kicker">{kicker}</p> : null}
          <h2 className="page-title mt-1">
            {title}
            {highlight ? (
              <>
                {' '}
                <span className="text-cyan">{highlight}</span>
              </>
            ) : null}
          </h2>
          {lede ? <p className="lede lede-wide">{lede}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </header>
  )
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="empty-note">{children}</p>
}
