import { RiRobot2Line } from "react-icons/ri";
import styles from './Message.module.css'

function getTime() {
  const d = new Date()
  return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0')
}

export default function Message({ message }) {
  const { role, content, time } = message
  const isAgent = role === 'assistant'
  const displayTime = time ?? getTime()

  return (
    <div className={`${styles.msgWrap} ${isAgent ? styles.msgWrapAgent : styles.msgWrapUser}`}>
      {isAgent && (
        <div className={styles.avatar} aria-hidden="true">
          <RiRobot2Line />
        </div>
      )}

      <div className={styles.msgContent}>
        <div 
          className={`${styles.bubble} ${isAgent ? styles.bubbleAgent : styles.bubbleUser}`}
          style={{ whiteSpace: "pre-wrap" }}
        >
          {content}
        </div>
        <div className={`${styles.time} ${isAgent ? styles.timeAgent : styles.timeUser}`}>
          {displayTime}
        </div>
      </div>
    </div>
  )
}