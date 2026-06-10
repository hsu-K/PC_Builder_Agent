import { useState } from 'react'
import HistoryItem from './HistoryItem'
import styles from './Sidebar.module.css'

export default function Sidebar({
  builds,
  activeBuildId,
  onSelect,
  onNewBuild,
  onDeleteItem 
}) {
  const [searchQuery, setSearchQuery] = useState('')

  const filtered = builds.filter(b =>
    b.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    b.tag.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const totalSpent = builds.reduce((sum, b) => {
    const partTotal = Object.values(b.parts).reduce((s, p) => s + p.price, 0)
    return sum + partTotal
  }, 0)

  return (
    <aside className={styles.sidebar}>

      {/* Header */}
      <div className={styles.header}>
        <div className={styles.logo}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
            aria-hidden="true">
            <rect x="4" y="4" width="6" height="6" rx="1" />
            <rect x="14" y="4" width="6" height="6" rx="1" />
            <rect x="4" y="14" width="6" height="6" rx="1" />
            <rect x="14" y="14" width="6" height="6" rx="1" />
          </svg>
          <span>PC Builder</span>
        </div>
        <div className={styles.statPill}>
          {builds.length} Builds
        </div>
      </div>

      {/* New build button */}
      <div className={styles.newBuildWrap}>
        <button className={styles.newBuildBtn} onClick={onNewBuild}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          Add Build
        </button>
      </div>

      {/* Search */}
      {builds.length > 3 && (
        <div className={styles.searchWrap}>
          <svg className={styles.searchIcon} width="13" height="13" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            className={styles.searchInput}
            type="text"
            placeholder="搜尋建置…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button className={styles.clearBtn} onClick={() => setSearchQuery('')} aria-label="清除搜尋">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
      )}

      {/* Section label */}
      <div className={styles.sectionLabel}>History</div>

      {/* History list */}
      <div className={styles.list}>
        {filtered.length === 0 ? (
          <div className={styles.empty}>Can't find the build</div>
        ) : (
          filtered.map(build => (
            <HistoryItem
              key={build.id}
              build={build}
              isActive={build.id === activeBuildId}
              onClick={() => onSelect(build.id)}
              onDeleteItem={onDeleteItem}
            />
          ))
        )}
      </div>

      {/* Footer */}
      <div className={styles.footer}>
        <div className={styles.footerLabel}>All Build Cost</div>
        <div className={styles.footerTotal}>
          NT${totalSpent.toLocaleString()}
        </div>
      </div>

    </aside>
  )
}