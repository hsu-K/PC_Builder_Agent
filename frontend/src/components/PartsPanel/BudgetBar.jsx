import styles from './PartsPanel.module.css'

export default function BudgetBar({ total, budget }) {
  const percent = Math.min(Math.round((total / budget) * 100), 100)
  const overBudget = total > budget
  const remaining = budget - total

  return (
    <div className={styles.budgetBar}>
      <div className={styles.budgetLabels}>
        <span className={styles.budgetLeft}>
          預算 NT${budget.toLocaleString()}
        </span>
        <span className={`${styles.budgetRight} ${overBudget ? styles.budgetOver : ''}`}>
          {overBudget
            ? `超出 NT$${Math.abs(remaining).toLocaleString()}`
            : `剩餘 NT$${remaining.toLocaleString()}`
          }
        </span>
      </div>
      <div className={styles.budgetTrack}>
        <div
          className={`${styles.budgetFill} ${overBudget ? styles.budgetFillOver : ''}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className={styles.budgetPercent}>{percent}% 已使用</div>
    </div>
  )
}