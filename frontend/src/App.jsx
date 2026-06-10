import Sidebar from './components/Sidebar/Sidebar'
import PartsPanel from './components/PartsPanel/PartsPanel'
import ChatPanel from './components/ChatPanel/ChatPanel'
import { ActiveChatProvider, useActiveChat } from './hooks/useActiveChat'

function AppContent() {
  const {
    chatHistory,
    activeChatId,
    activeChat,
    changeChat,
    addNewBuild,
    deleteBuild,
    updatePart,
    updateChat,
    setPreference,
  } = useActiveChat()

  const activeChatOptions = activeChat?.options ?? {}
  const activeChatMessages = activeChat?.messages ?? []
  const activeChatPreference = activeChat?.preference ?? {}

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
        id={activeChatId}
        messages={activeChatMessages}
        preference={activeChatPreference}
        onBuildUpdate={updateChat}
        onPreferenceUpdate={setPreference}
      />
    </div>
  )
}

export default function App() {
  return (
    <ActiveChatProvider>
      <AppContent />
    </ActiveChatProvider>
  )
}
