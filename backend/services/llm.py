import os
from google import genai

def get_genai_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set")
    return genai.Client(api_key=api_key)

def generate_response(system_prompt: str, context: str, query: str) -> str:
    """
    Generate a response using Gemini 2.5 Flash.
    """
    client = get_genai_client()
    
    # Combine context and query
    user_prompt = f"Context about the patient:\n{context}\n\nUser Query:\n{query}"
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.4, # slightly lower for medical/support context to reduce hallucinations
        ),
    )
    return response.text

def generate_chat_response(system_prompt: str, chat_history: list, query: str) -> str:
    """
    Generate a conversational response using chat history.
    chat_history should be a list of dicts: [{'role': 'user'/'model', 'parts': ['text']}]
    """
    client = get_genai_client()
    
    # We will format the history into a single prompt for simplicity or use the chat API
    history_text = "\n".join([f"{msg['role'].capitalize()}: {msg['parts'][0]}" for msg in chat_history])
    user_prompt = f"Previous Conversation:\n{history_text}\n\nUser Query:\n{query}"
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.6, # slightly higher for conversational flow
        ),
    )
    return response.text
