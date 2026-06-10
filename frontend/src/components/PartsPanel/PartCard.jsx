import {ICONS} from '../Icon/PartsIcon'
import styles from './PartsPanel.module.css'

export default function PartCard({ partKey, part, icon, options, onUpdate }) {
  const handleChange = (e) => {
    const selected = options.find(o => o.name === e.target.value)
    if (selected) onUpdate(partKey, { ...selected, category: part.category })
  }

  const isRecommended = options.find(o => o.name === part.name)?.recommended

  return (
    <div className={`${styles.card} ${isRecommended ? styles.cardHighlighted : ''}`}>
      <div className={styles.cardRow}>
        <div className={styles.cardIcon} aria-hidden="true">
          {ICONS[icon] ?? ICONS.default}
        </div>
        <div className={styles.cardInfo}>
          <div className={styles.cardCategory}>{part.category}</div>
          <div className={styles.cardName} title={part.name}>{part.name}</div>
        </div>
        <div className={styles.cardPrice}>
          NT${(part.price)? part.price.toLocaleString() : '???'}
        </div>
      </div>

      <div className={styles.selectWrap}>
        <select
          className={styles.select}
          value={options.length ? part.name : ''}
          onChange={handleChange}
          aria-label={`選擇${part.category}`}
          disabled={options.length === 0}
        >
          {options.length === 0 ? (
            <option value="">No parts</option>
          ) : (
            options.map(opt => (
              <option key={opt.name} value={opt.name}>
                {opt.recommended ? '✦ ' : ''}{opt.name} — NT${(opt.price)? opt.price.toLocaleString(): '???'}
              </option>
            ))
          )}
        </select>
        <svg className={styles.selectChevron} width="10" height="10" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
          aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      <div className={styles.cardDetail}>
        Part description:
        <br></br>
        
        {part.detail}
      </div>
      
      <div className={styles.cardSource}>
        Source:
        <br></br>
        <ul>
          { part.sources?.map((i, source) => (
              <li key={i}><a href={source.url}>{source.title}</a></li>
            ))
          }

        </ul>
      </div>
    </div>
  )
}