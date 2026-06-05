import { useCallback, useEffect, useState } from 'react'
import Sidebar from './components/Sidebar/Sidebar'
import PartsPanel from './components/PartsPanel/PartsPanel'
import ChatPanel from './components/ChatPanel/ChatPanel'
import { useLocalStorage } from './hooks/useLocalStorage'

const DEFAULT_CHAT = {
  id: 0,
  title: 'Default',
  parts: {},
  budget: 0,
  tag: '',
  options: [],
  messages: [],
}

export default function App() {
  const [chatHistory, setChatHistory] = useLocalStorage("chatHistory", [DEFAULT_CHAT])
  const [activeChatId, setActiveChatId] = useLocalStorage("activeChatId", chatHistory[0]?.id ?? 1)
  const activeChat = chatHistory.find(c => c.id === activeChatId) ?? chatHistory[0]
  const activeChatOptions = activeChat?.options ?? {}
  const activeChatMessages = activeChat?.messages ?? []

  useEffect(() => {
    if (!activeChat && chatHistory.length > 0) {
      setActiveChatId(chatHistory[0].id)
    }
  }, [activeChat, chatHistory, setActiveChatId])


  const updateChat = useCallback((changes) => {
    setChatHistory(prev => prev.map(chat =>
      chat.id === activeChatId
        ? { ...chat, ...changes }
        : chat
    ))
  }, [activeChatId])

  const updateBuild = useCallback((changes) => {
    updateChat(changes)
  }, [updateChat])

  const updatePart = useCallback((partKey, newPart) => {
    updateChat({ parts: { ...activeChat.parts, [partKey]: newPart } })
  }, [activeChat.parts, updateChat])

  const updateParts = useCallback((newParts) => {
    updateChat({ parts: { ...activeChat.parts, ...newParts } })
  }, [activeChat.parts, updateChat])

  const handleMessagesChange = useCallback((msgs) => {
    updateChat({ messages: msgs })
  }, [updateChat])

  const changeChat = (buildId) => {
    setActiveChatId(buildId)
  }

  const addNewBuild = () => {
    const newId = Date.now()  // 用時間戳，簡單又不會重複
    const newChat = {
      ...DEFAULT_CHAT,
      id: newId,
      title: `New Build ${newId}`,
    }
    setChatHistory(prev => [...prev, newChat])
    setActiveChatId(newId)
  }

  const deleteBuild = (id) => {
    if (confirm('Do you really want to DELETE this build?')) {
      setChatHistory(prev => prev.filter(chat => chat.id !== id))

      if (activeChatId === id && chatHistory.length > 1) {
        const nextChat = chatHistory.find(chat => chat.id !== id)
        setActiveChatId(nextChat.id)
      }
    }
  }

  return (
    <div className="app">
      <Sidebar
        builds={chatHistory}
        activeBuildId={activeChatId}
        onSelect={changeChat}
        onNewBuild={addNewBuild}
        onDeleteItem={deleteBuild}
      />
      
      <PartsPanel
        build={activeChat}
        partOptions={activeChatOptions}
        onUpdatePart={updatePart}
      />

      <ChatPanel
        key={activeChatId}
        messages={activeChatMessages}
        onBuildUpdate={updateBuild}
      />
    </div>
  )
}