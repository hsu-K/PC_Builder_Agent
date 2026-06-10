import { createContext, createElement, useCallback, useContext, useEffect, useMemo } from 'react'
import { useLocalStorage } from './useLocalStorage'

const DEFAULT_CHAT = {
  id: 0,
  title: 'Default',
  parts: {},
  budget: 0,
  tag: '',
  options: {},
  preference: {},
  messages: [],
  articles: [],
}

const ActiveChatContext = createContext(null)

export function ActiveChatProvider({ children }) {
  const [chatHistory, setChatHistory] = useLocalStorage('chatHistory', [DEFAULT_CHAT])
  const [activeChatId, setActiveChatId] = useLocalStorage('activeChatId', chatHistory[0]?.id ?? DEFAULT_CHAT.id)

  const activeChat = chatHistory.find((chat) => chat.id === activeChatId) ?? chatHistory[0]

  useEffect(() => {
    if (!activeChat && chatHistory.length > 0) {
      setActiveChatId(chatHistory[0].id)
    }
  }, [activeChat, chatHistory, setActiveChatId])

  const updateChat = useCallback(
    (changes) => {
      setChatHistory((prev) =>
        prev.map((chat) => (chat.id === activeChatId ? { ...chat, ...changes } : chat))
      )
    },
    [activeChatId, setChatHistory]
  )

  const updatePart = useCallback(
    (partKey, newPart) => {
      updateChat({ parts: { ...activeChat.parts, [partKey]: newPart } })
    },
    [activeChat.parts, updateChat]
  )

  const updateParts = useCallback(
    (newParts) => {
      updateChat({ parts: { ...activeChat.parts, ...newParts } })
    },
    [activeChat.parts, updateChat]
  )

  const setPreference = useCallback(
    (preference) => {
      const updates = { preference: { ...activeChat.preference, ...preference } }
      // 同步 preference.budget 到頂層 budget，讓 PartsPanel 的 BudgetBar 顯示正確預算
      if (preference.budget !== undefined) {
        updates.budget = Number(preference.budget) || 0
      }
      updateChat(updates)
    },
    [activeChat.preference, updateChat]
  )

  const setArticles = useCallback(
    (articles) => {
      updateChat({ articles })
    },
    [updateChat]
  )

  const handleMessagesChange = useCallback(
    (messages) => {
      updateChat({ messages })
    },
    [updateChat]
  )

  const changeChat = useCallback(
    (buildId) => {
      setActiveChatId(buildId)
    },
    [setActiveChatId]
  )

  const addNewBuild = useCallback(() => {
    const newId = crypto.randomUUID()
    const newChat = {
      ...DEFAULT_CHAT,
      id: newId,
      title: `New Build ${newId}`,
    }
    setChatHistory((prev) => [...prev, newChat])
    setActiveChatId(newId)
  }, [setChatHistory, setActiveChatId])

  const deleteBuild = useCallback(
    (buildId) => {
      setChatHistory((prev) => prev.filter((chat) => chat.id !== buildId))
      if (activeChatId === buildId && chatHistory.length > 1) {
        const nextChat = chatHistory.find((chat) => chat.id !== buildId)
        if (nextChat) setActiveChatId(nextChat.id)
      }
    },
    [activeChatId, chatHistory, setActiveChatId, setChatHistory]
  )

  const value = useMemo(
    () => ({
      chatHistory,
      activeChatId,
      activeChat,
      updateChat,
      updatePart,
      updateParts,
      setPreference,
      setArticles,
      handleMessagesChange,
      changeChat,
      addNewBuild,
      deleteBuild,
    }),
    [
      chatHistory,
      activeChatId,
      activeChat,
      updateChat,
      updatePart,
      updateParts,
      setPreference,
      setArticles,
      handleMessagesChange,
      changeChat,
      addNewBuild,
      deleteBuild,
    ]
  )

  return createElement(ActiveChatContext.Provider, { value }, children)
}

export function useActiveChat() {
  const context = useContext(ActiveChatContext)
  if (!context) {
    throw new Error('useActiveChat must be used within ActiveChatProvider')
  }
  return context
}
