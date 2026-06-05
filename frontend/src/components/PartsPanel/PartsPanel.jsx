import BudgetBar from './BudgetBar'
import PartCard from './PartCard'
import styles from './PartsPanel.module.css'

const PART_META = {
  cpu:    { label: 'CPU',   icon: 'cpu' },
  gpu:    { label: 'GPU',   icon: 'gpu' },
  mb:     { label: 'Mother Board',      icon: 'mb' },
  ram:    { label: 'RAM',   icon: 'ram' },
  ssd:    { label: 'SSD',   icon: 'ssd' },
  psu:    { label: 'PSU',   icon: 'psu' },
  case:   { label: 'Case',  icon: 'case' },
  cooler: { label: 'Cooler',      icon: 'cooler' },
}

export default function PartsPanel({ 
  build,
  partOptions,
  onUpdatePart 
}) {
  const total = Object.values(build.parts).reduce((sum, p) => sum + p.price, 0)
  const overBudget = total > build.budget
  const currParts = build.parts

  const handleExport = () => {
    const lines = [
      `Title：${build.name}`,
      `Budget：NT$${build.budget.toLocaleString()}`,
      `Cost：NT$${total.toLocaleString()}`,
      '',
      ...Object.entries(build.parts).map(([key, part]) =>
        `${PART_META[key]?.label ?? key}：${part.name}  NT$${part.price.toLocaleString()}`
      )
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${build.name}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={styles.panel}>

      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.titleRow}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
              aria-hidden="true">
              <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
            </svg>
            <span className={styles.title}>{build.title}</span>
          </div>
        </div>
        <BudgetBar total={total} budget={build.budget} />
      </div>

      {/* Parts list */}
      <div className={styles.list}>

        {Object.keys(PART_META).map(key => (
          <PartCard
            key={key}
            partKey={key}
            part={{ ...currParts[key], category: PART_META[key]?.label ?? key }}
            icon={PART_META[key]?.icon ?? 'default'}
            options={partOptions[key] ?? []}
            onUpdate={onUpdatePart}
          />
        ))}
      </div>

      {/* Footer */}
      <div className={styles.footer}>
        <div>
          <div className={styles.totalLabel}>Total</div>
          <div className={`${styles.total} ${overBudget ? styles.totalOver : ''}`}>
            NT${total.toLocaleString()}
            {overBudget && (
              <span className={styles.overBadge}>over budget</span>
            )}
          </div>
        </div>
        <button className={styles.exportBtn} onClick={handleExport}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            aria-hidden="true">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Export Build
        </button>
      </div>

    </div>
  )
}