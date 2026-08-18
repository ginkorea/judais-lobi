# core/runtime/messages.py — System prompt, chat context, and the wire
# shape of one assistant turn

"""What goes to the model, in the shapes a server takes back.

The system prompt and the chat context are the two this module has always
built.  The third is newer and is the reason for the ``json`` import
below: **the assistant turn a native-protocol loop hands back**, and the
tool calls it carries.

That turn has one owner because it has to.  A native round trip is the
provider quoting the model to itself — the loop appends the model's own
decision to the conversation and sends it again with the results — and a
provider is entitled to put things on a tool call that this repo has
never heard of.  A signature over the call's reasoning, a vendor's
``extra_content`` block, a routing id: some of them are *required back,
verbatim, in the position they arrived in*, and a loop that rebuilt the
turn out of the two fields it understood would send a call the provider
refuses.  That is not hypothetical — see ``EVAL.md`` §12, where every
mission of the ``native`` row died on the turn after the first tool call.

So the rule is: **whatever this repo did not name is kept and given back
untouched.**  :data:`CALL_KEYS` and :data:`FUNCTION_KEYS` are the names it
understands; :func:`opaque_extra` collects everything else,
:func:`tool_call_object` puts it back where it was, and neither of them
ever looks inside it.  The mapping mirrors the object it came from, so a
key that arrived on the ``function`` sub-object goes back on the
``function`` sub-object and not beside it.

One owner, applied by each backend's normaliser
(:func:`~core.runtime.backends.base.tool_calls_from`), by the loop that
rebuilds the turn (:meth:`core.runtime.run.Run._assistant_turn`) and by
the resume that rebuilds it from a log
(:func:`core.runtime.resume._rebuild_native`).  Three spellings of "what a
tool call looks like on the wire" is three chances to disagree about it.
"""

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

#: The keys this repo understands on a provider's tool-call object.
#: Everything else on one is opaque and travels through
#: :func:`opaque_extra`.
CALL_KEYS = ("id", "type", "function")

#: The keys this repo understands on a tool call's ``function``.
FUNCTION_KEYS = ("name", "arguments")

#: The key :func:`opaque_extra` nests the ``function`` object's own unknown
#: keys under.  Collision-free by construction: ``function`` is a name this
#: repo *does* understand at the call level, so it is never itself
#: collected as an unknown one.
NESTED = "function"


def plain_mapping(payload: Any) -> Optional[Dict[str, Any]]:
    """*payload* as a plain dict, whatever object shape it arrived in.

    A JSON backend hands over ``dict``s; an SDK hands over pydantic
    models.  Both are read here rather than at every site that wants to
    walk a provider object's keys — the same bargain
    :func:`core.runtime.backends.base._as_mapping` strikes for usage, and
    now the half of it that is not about usage.

    ``None`` for anything that cannot be read as a mapping at all.
    """
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        return dict(payload)
    for name in ("model_dump", "to_dict", "dict"):
        method = getattr(payload, name, None)
        if not callable(method):
            continue
        try:
            got = method()
        except Exception:               # pragma: no cover - defensive
            continue
        if isinstance(got, Mapping):
            return dict(got)
    return None


def opaque_extra(call: Any, function: Any = None,
                 known: Sequence[str] = CALL_KEYS) -> Dict[str, Any]:
    """Everything the provider put on a tool call that this repo cannot name.

    A mapping shaped like the object it was read from, with the understood
    keys removed: unknown keys of the call at the top, unknown keys of its
    ``function`` under :data:`NESTED`.  Empty when there were none — and
    **empty is the normal case**, which is why every caller stores it only
    when it is not, so that a provider sending nothing extra produces
    byte-identical records to the ones this tree wrote before any of this
    existed.

    ``None`` values are dropped.  An SDK model dumps its unset optional
    fields as ``None``, and echoing a wall of nulls back at a server is not
    fidelity; a field that was absent stays absent.

    *known* is a parameter because a shape can differ while the rule does
    not: a streamed fragment also carries ``index``, and an Anthropic
    ``tool_use`` block carries its name and input at the top level.  What is
    understood is the caller's to say; that the rest is kept is not.
    """
    mapping = plain_mapping(call) or {}
    extra = {key: value for key, value in mapping.items()
             if key not in known and value is not None}
    nested = plain_mapping(function) or {}
    inner = {key: value for key, value in nested.items()
             if key not in FUNCTION_KEYS and value is not None}
    if inner:
        extra[NESTED] = inner
    return extra


def merge_extra(base: Mapping[str, Any],
                more: Mapping[str, Any]) -> Dict[str, Any]:
    """Two opaque mappings, later wins, one level of nesting respected.

    For the streamed case: a provider may put its opaque field on the frame
    that opened the call and the arguments on the frames after it, or the
    other way round, and the reassembled call has to end up with both.
    Nothing is interpreted here either — this is a dict update that knows
    :data:`NESTED` is a sub-object and not a value.
    """
    out = dict(base or {})
    for key, value in (more or {}).items():
        if (key == NESTED and isinstance(value, Mapping)
                and isinstance(out.get(key), Mapping)):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def tool_call_object(call_id: str, name: str, arguments: Any,
                     extra: Optional[Mapping[str, Any]] = None,
                     ) -> Dict[str, Any]:
    """One tool call in the shape a server takes back, extras replaced.

    The inverse of :func:`opaque_extra`, and the only place this repo
    writes the OpenAI tool-call wire shape down.  The understood keys
    first, in the order they have always been emitted in, then whatever the
    provider added — so a call with nothing extra serializes byte for byte
    as it did before this function existed.
    """
    rest = dict(extra or {})
    inner = rest.pop(NESTED, None)
    function: Dict[str, Any] = {"name": name, "arguments": arguments}
    if isinstance(inner, Mapping):
        function.update(inner)
    call: Dict[str, Any] = {"id": call_id, "type": "function",
                            "function": function}
    call.update(rest)
    return call


def arguments_text(call: Mapping[str, Any]) -> str:
    """A call's arguments as the JSON string a request carries.

    The provider's own text when it is still around — ``raw`` on a call the
    loop normalized, ``arguments_raw`` on one straight off
    :func:`~core.runtime.backends.base.tool_calls_from` — and a
    re-serialization of the parsed object otherwise.  What goes back to the
    model as its own turn should be what the model emitted, down to the key
    order: a re-serialization is a paraphrase of the model to itself.
    """
    raw = call.get("raw", call.get("arguments_raw"))
    if isinstance(raw, str):
        return raw
    return json.dumps(call.get("arguments") or {}, ensure_ascii=False)


def assistant_turn(reply: str,
                   calls: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """The model's own turn, in the shape a server will take back.

    ``content`` and ``tool_calls`` together, because a harmony model emits
    both — the reasoning-flavoured preamble and the call — and a turn that
    dropped the text would hand the model back a version of itself that
    never explained anything.  No ``tool_calls`` key at all when there were
    none: an empty list is a different thing to some servers, and this is
    the shape a reply with no calls in it takes.

    Each call is a mapping with ``id``, ``name`` (or ``tool``) and
    ``arguments``, plus the optional ``raw`` and ``extra`` that
    :func:`arguments_text` and :func:`tool_call_object` own.
    """
    message: Dict[str, Any] = {"role": "assistant", "content": reply}
    listed = list(calls or [])
    if listed:
        message["tool_calls"] = [
            tool_call_object(
                str(call.get("id") or ""),
                str(call.get("name") or call.get("tool") or ""),
                arguments_text(call),
                call.get("extra"),
            )
            for call in listed
        ]
    return message


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
