import { useEffect, useRef, useState } from 'react'
import { useChat } from '../../hooks/useChat'
import Message from './Message'
import ChatInput from './ChatInput'
import styles from './ChatPanel.module.css'

const INITIAL_MESSAGE = {
  role: 'assistant',
  content: '你好！我是你的 PC 建置助手。請告訴我你的使用需求和預算，我來幫你規劃最適合的配置。',
  time: null,
}

const SUGGESTIONS = [
  '幫我規劃一台電競電腦，預算 NT$60,000',
  '我需要一台影片剪輯工作站',
  '預算 NT$25,000 有什麼推薦？',
]

export default function ChatPanel({ 
  //currBuild,
  messages: initialMessages = [],
  onBuildUpdate,
}) {
  const { messages, isLoading, sendMessage } = useChat(initialMessages)
  const [ suggestions, setSuggestions ] = useState(SUGGESTIONS)
  const bottomRef = useRef(null)

  // 每次訊息更新自動捲到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const handleSend = (text) => {
    sendMessage(
      text,
      //currBuild,
      onBuildUpdate,
    )
  }

  const showSuggestions = messages.length === 0

  return (
    <div className={styles.panel}>

      {/* Header */}
      <div className={styles.header}>
        <div className={styles.agentInfo}>
          <span className={styles.agentDot} aria-hidden="true" />
          <span className={styles.agentName}>PC Agent</span>
        </div>
        <span className={styles.agentStatus}>上線中</span>
      </div>

      {/* Messages */}
      <div className={styles.messages} role="log" aria-live="polite" aria-label="對話訊息">

        {/* 初始歡迎訊息 */}
        <Message message={INITIAL_MESSAGE} />

        {/* 快速建議 chips（只在對話開始前顯示） */}
        {showSuggestions && (
          <div className={styles.suggestions}>
            {suggestions.map((s) => (
              <button
                key={s}
                className={styles.chip}
                onClick={() => handleSend(s)}
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {/* 對話訊息列表 */}
        {messages.map((msg, i) => (
          <Message key={i} message={msg} />
        ))}

        {/* 打字中動畫 */}
        {isLoading && (
          <div className={styles.typingWrap}>
            <div className={styles.typing}>
              <span className={styles.dot} />
              <span className={styles.dot} />
              <span className={styles.dot} />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <ChatInput onSend={handleSend} disabled={isLoading} />

    </div>
  )
}