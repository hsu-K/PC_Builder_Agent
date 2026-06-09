import { useEffect, useState } from 'react'

export function useChat(initialMessages = []) {
  const [messages, setMessages] = useState(initialMessages)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    const shouldSync =
      initialMessages.length !== messages.length ||
      initialMessages.some((msg, idx) =>
      msg.role !== messages[idx]?.role || msg.content !== messages[idx]?.content
  )

    if (shouldSync) {
      setMessages(initialMessages)
    }
  }, [initialMessages, messages])

  let useMock = false
  let response = {}

  const sendMessage = async (
    id,
    text,
    onBuildUpdate,
    preference = {},
    pc_board_response=''
  ) => {
      const newMessages = [...messages, { role: 'user', content: text }]
      setMessages(newMessages)
      onBuildUpdate?.({ messages: newMessages })
      setIsLoading(true)

    try {
      if(!useMock){
        const body = { 
          id: id,
          messages: newMessages,
          preference: preference,
          pc_board_response: pc_board_response?? ""
        }
        const fetchResponse = await fetch('http://localhost:8000/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        console.log('request body', body)
        if (!fetchResponse.ok) {
          const errorData = await fetchResponse.json().catch(() => null)
          throw new Error(errorData?.error || fetchResponse.statusText)
        }
        response = await fetchResponse.json()
        console.log('response body', response)
      }
      else{
        response = {
          message: text,
          title: "標題",
          parts: Object.fromEntries(
            Object.entries(mockOptions).map(([key, opts]) => [key, opts[0]])
          ),
          budget: 50000,
          options: mockOptions,
          suggestions: [
            '幫我規劃一台電競電腦，預算 NT$60,000',
            '我需要一台影片剪輯工作站',
            '預算 NT$25,000 有什麼推薦？',
          ]
        }
      }

      const assistantMessage = { role: 'assistant', content: response.message }
      const updatedMessages = [...newMessages, assistantMessage]
      setIsLoading(false)
      setMessages(updatedMessages)

      const updatePayload = { messages: updatedMessages }
      if (response.title !== undefined) updatePayload.title = response.title
      if (response.parts !== undefined) updatePayload.parts = response.parts
      if (response.options !== undefined) updatePayload.options = response.options
      if (response.budget !== undefined) updatePayload.budget = response.budget
      if (response.suggestions !== undefined) updatePayload.suggestions = response.suggestions
      if (response.pc_board_response !== undefined) updatePayload.pc_board_response = response.pc_board_response
      onBuildUpdate?.(updatePayload)

    } catch (e) {
      setIsLoading(false)
      console.log(e)
      const errorMessage = { role: 'assistant', content: 'Fail to response, please try again.\n' + e }
      const errorMessages = [...newMessages, errorMessage]
      setMessages(errorMessages)
      onBuildUpdate?.({ messages: errorMessages })
    }
  }

  return { messages, isLoading, sendMessage }
}

const mockOptions = {
  cpu: [
    { name: 'Intel Core i7-14700K', price: 11500, detail: "元件介紹 1", sources:[{title: "cpu 分析 1", url: ""} ], recommended: true},
    { name: 'Intel Core i9-14900K', price: 18900, detail: "元件介紹 2", sources:[{title: "cpu 分析 2", url: ""} ]},
    { name: 'AMD Ryzen 9 ',    price: 14800, detail: "元件介紹 3", sources:[{title: "cpu 分析 3", url: ""} ]},
  ],
  gpu: [
    { name: 'NVIDIA RTX 4070 Ti',     price: 22900, detail: "元件介紹", sources:[{title: "gpu 分析", url: ""} ], recommended: true},
    { name: 'NVIDIA RTX 4070 Super',  price: 18500, detail: "元件介紹", sources:[{title: "gpu 分析", url: ""} ]},
    { name: 'AMD RX 7900 GRE',        price: 16200, detail: "元件介紹"},
  ],
  mb: [
    { name: 'ASUS ROG Strix Z790-F',         price: 9800, detail: "元件介紹", sources:[{title: "mb 分析", url: ""} ], recommended: true },
  ],
  ram: [
    { name: 'Corsair 32GB DDR5-6000',  price: 4200, detail: "元件介紹", recommended: true},
    { name: 'G.Skill 64GB DDR5-6400',  price: 8800, detail: "元件介紹"},
    { name: 'Kingston 32GB DDR5-5600', price: 3600, detail: "元件介紹"},
  ],
  ssd: [
    { name: 'Samsung 990 Pro 2TB',      price: 5200, detail: "元件介紹", recommended: true},
    { name: 'WD Black SN850X 2TB',      price: 4800, detail: "元件介紹"},
  ],
  psu: [
    { name: 'Corsair RM850x 850W',              price: 4800, detail: "元件介紹", recommended: true},
    { name: "be quiet! Straight Power 11 750W", price: 4200, detail: "元件介紹"},
  ],
  case: [
    { name: 'Lian Li PC-O11 Dynamic',    price: 4000, detail: "元件介紹", recommended: true},
    { name: 'Fractal Design Meshify 2',  price: 4500, detail: "元件介紹"},
  ],
  cooler: [
    { name: 'Noctua NH-D15',          price: 3200 ,detail: "元件介紹", recommended: true},
    { name: 'be quiet! Dark Rock 4',  price: 2800 ,detail: "元件介紹"},
    { name: 'NZXT Kraken X63',        price: 4200 ,detail: "元件介紹"},
  ],
}