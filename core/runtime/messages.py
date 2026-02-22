# core/runtime/messages.py — System prompt and chat context assembly

from typing import Callable, Dict, List, Optional


def build_system_prompt(
    system_message: str,
    tool_names: List[str],
    describe_tool_fn: Callable[[str], Dict],
    examples: List,
) -> str:
    """Assemble system prompt from message, tool descriptions, and examples."""
    tool_info = "\n".join(
        f"- {name}: {describe_tool_fn(name)['description']}"
        for name in tool_names
    )
    examples_text = "\n\n".join(
        f"User: {ex[0]}\nAssistant: {ex[1]}" for ex in examples
    )
    return (
        f"{system_message}\n\n"
        "You have the following tools (do not call them directly):\n"
        f"{tool_info}\n\n"
        "Tool results appear in history as assistant messages; treat them as your own work.\n\n"
        f"Here are examples:\n\n{examples_text}"
    )


def build_chat_context(
    system_prompt: str,
    history: List[Dict[str, str]],
    invoked_tools: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Build the message list sent to the backend.

    Replaces history[0] (system message) with the full system_prompt,
    appends tool-context annotation if invoked_tools is provided.
    """
    prompt = system_prompt
    if invoked_tools:
        prompt += (
            "\n\n[Tool Context] "
            f"{', '.join(invoked_tools)} results are available above.\n"
        )
    return [{"role": "system", "content": prompt}] + history[1:]
