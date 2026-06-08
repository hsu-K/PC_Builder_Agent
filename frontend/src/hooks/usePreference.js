import { useEffect, useState } from 'react'

let [isLoading, setIsLoading] = useState(false)

export const setPreference = async (
    preference,
) => {
    /*
    setIsLoading(true)

    try {
        const body = {...preference}
        const fetchResponse = await fetch('http://localhost:8000/set_preference', {
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

        const assistantMessage = { role: 'assistant', content: response.message }
        const updatedMessages = [...newMessages, assistantMessage]
        setIsLoading(false)
        setMessages(updatedMessages)
    } catch (e) {
        setIsLoading(false)
        console.log(e)
        const errorMessage = { role: 'assistant', content: 'Fail to response, please try again.\n' + e }
        const errorMessages = [...newMessages, errorMessage]
        setMessages(errorMessages)
        onBuildUpdate?.({ messages: errorMessages })
    }
    */
}
