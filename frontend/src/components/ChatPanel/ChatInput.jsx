import { useState, useRef, useEffect } from 'react'
import { BsThreeDotsVertical } from 'react-icons/bs'
import { HiOutlineTemplate } from 'react-icons/hi'
import { MdOutlineGames, MdOutlineWork, MdOutlineAttachMoney, MdOutlineVideoLibrary } from 'react-icons/md'
import TemplatePanel from './TemplatePanel'
import styles from './ChatPanel.module.css'


export default function ChatInput({ id, preference, onSend, disabled, onSavePreference }) {
  const [text, setText] = useState('')
  const [showMenu, setShowMenu] = useState(false)
  const [showTemplates, setShowTemplates] = useState(false)
  const textareaRef = useRef(null)
  const menuRef = useRef(null)
  const templateRef = useRef(null)

  // 點選外部關閉 menu
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setShowMenu(false)
      }
      if (templateRef.current && !templateRef.current.contains(e.target)) {
        setShowTemplates(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = (e) => {
    setText(e.target.value)
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 96) + 'px'
    }
  }

  const applyTemplate = (templateText) => {
    setText(templateText)
    setShowTemplates(false)
    setShowMenu(false)
    textareaRef.current?.focus()
  }

  /*
  // 從模板選完後填入輸入框
  const handleTemplateSelect = (templateText) => {
    setText(templateText)
    setShowTemplates(false)
    textareaRef.current?.focus()
  }
  */

  // 直接發送訊息並回覆已設定預設偏好（不進入輸入框，僅顯示，不跑模型）
  const handleTemplateSelect = (templateText) => {
    onSend(templateText, false, "已更新偏好設定：" + templateText)
    setShowTemplates(false)
    textareaRef.current?.focus()
  }

  return (
    <div className={styles.inputArea}>

      {/* Template 面板 */}
      {showTemplates && (
        <TemplatePanel id={id} preference={preference} onSelect={handleTemplateSelect} onSavePreference={onSavePreference} />
      )}
      {/* 工具列 */}
      <div className={styles.toolbar}>
        <button
          className={`${styles.toolBtn} ${showTemplates ? styles.toolBtnActive : ''}`}
          onClick={() => { setShowTemplates(prev => !prev); setShowMenu(false) }}
          title="需求模板"
        >
          <HiOutlineTemplate size={14} />
          <span>templete</span>
        </button>

        {/* 更多選項 */}
        <div className={styles.moreWrap} ref={menuRef}>
          <button
            className={`${styles.toolBtn} ${showMenu ? styles.toolBtnActive : ''}`}
            onClick={() => { setShowMenu(prev => !prev); setShowTemplates(false) }}
            title="更多"
          >
            <BsThreeDotsVertical size={14} />
          </button>
          {showMenu && (
            <div className={styles.moreMenu}>
              <button className={styles.moreMenuItem} onClick={() => { setText(''); setShowMenu(false) }}>
                清空輸入
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 輸入框 */}
      <div className={`${styles.inputWrap} ${disabled ? styles.inputWrapDisabled : ''}`}>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          placeholder={disabled ? 'Agent replying...' : 'Describe your demands (e.g. Build a PC for 3A games, model training, or preferred brands)'}
          value={text}
          rows={1}
          disabled={disabled}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          aria-label="inputMessage"
        />
        <button
          className={styles.sendBtn}
          onClick={handleSend}
          disabled={!text.trim() || disabled}
          aria-label="sendMessage"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            aria-hidden="true">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>

      <div className={styles.inputHint}>Enter: Send　Shift+Enter: NewLine</div>
    </div>
  )
}