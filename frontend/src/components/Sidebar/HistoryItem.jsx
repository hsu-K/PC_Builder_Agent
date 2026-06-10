import styles from './Sidebar.module.css'
import { HiEllipsisVertical } from "react-icons/hi2";
import { HiTrash } from "react-icons/hi2";


const TAG_STYLES = {
  電競: styles.tagGaming,
  工作: styles.tagWork,
  預算: styles.tagBudget,
  創作: styles.tagCreate,
}

export default function HistoryItem({ build, isActive, onClick,  onDeleteItem}) {
  const total = Object.values(build.parts).reduce((sum, p) => sum + p.price, 0)
  const partCount = Object.keys(build.parts).length
  const budgetPercent = Math.round((total / build.budget) * 100)
  const overBudget = total > build.budget

  return (
    <div>
      <div
        className={`${styles.item} ${isActive ? styles.itemActive : ''}`}
        onClick={onClick}
        aria-current={isActive ? 'true' : undefined}
      >
        <div className={styles.itemTop}>
          <span className={styles.itemName}>{build.title}</span>
          {build.tag && (
            <span className={`${styles.tag} ${TAG_STYLES[build.tag] ?? styles.tagDefault}`}>
              {build.tag}
            </span>
          )}
          <button
            className={styles.itemSetting}
            onClick={(e) => {
              e.stopPropagation()
              onDeleteItem(build.id)
            }}
             aria-label="刪除配置"  
          >
            <HiTrash/>
          </button>
        </div>

        <div className={styles.itemMeta}>
          <span className={overBudget ? styles.overBudget : styles.itemPrice}>
            NT${total.toLocaleString()}
          </span>
          <span className={styles.itemParts}>{partCount} 個零件</span>
        </div>

        {/* Mini budget bar */}
        <div className={styles.miniBar}>
          <div
            className={`${styles.miniFill} ${overBudget ? styles.miniFillOver : ''}`}
            style={{ width: `${Math.min(budgetPercent, 100)}%` }}
          />
        </div>

        <div className={styles.itemBudgetLabel}>
          {overBudget
            ? `超出預算 NT${(total - build.budget).toLocaleString()}`
            : `預算剩餘 NT$${(build.budget - total).toLocaleString()}`
          }
        </div>
      </div>
    </div>
  )
}