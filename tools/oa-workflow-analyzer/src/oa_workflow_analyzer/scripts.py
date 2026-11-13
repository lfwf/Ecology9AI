"""Offline layout decoding and conservative JavaScript evidence collection.

This is a lexical evidence scanner, not a JavaScript interpreter. It never evaluates
source, imports OA classes, resolves external modules, or requests network resources.
The E-Design profile describes an export format, not credential material.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re


_PROFILE = "weaver-e9-edesign-aes-cbc-v1"
_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.I | re.S)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blank(text: str) -> str:
    return "".join(char if char in "\r\n" else " " for char in text)


def _script_source(text: str) -> str:
    """Remove HTML wrappers without changing character positions or line numbers."""
    if re.search(r"<script\b", text, re.I):
        source = list(_blank(text))
        for match in _SCRIPT.finditer(text):
            source[match.start(1):match.end(1)] = match.group(1)
        return "".join(source)
    if re.match(r"\s*<(?:!doctype|html|div|body|span)\b", text, re.I):
        return _blank(text)
    return text


def decode_layout_text(value: str) -> dict:
    """Read plaintext or the recognized E9 hex/AES export profile.

    Unsupported data stays explicitly unsupported; hashes allow callers to link
    it to source evidence without putting opaque or sensitive payloads in reports.
    CR/LF sequences are retained so original source line numbering is reproducible.
    """
    result = {"text": "", "status": "unsupported", "encoding": None,
              "profile": None, "input_sha256": _hash(value.encode("utf-8"))}
    stripped = value.strip()
    if re.fullmatch(r"[0-9a-fA-F]+", stripped or " "):
        result["profile"] = _PROFILE
        try:
            data = bytes.fromhex(stripped)
            if not data or len(data) % 16:
                raise ValueError("E-Design ciphertext must contain whole AES blocks")
            # Optional local library; lack of it is an explicit partial result.
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            decryptor = Cipher(algorithms.AES(b"WEAVER E-DESIGN."),
                               modes.CBC(b"weaver e-design.")).decryptor()
            decoded = decryptor.update(data) + decryptor.finalize()
            padding = decoded[-1]
            if not 1 <= padding <= 16 or decoded[-padding:] != bytes([padding]) * padding:
                raise ValueError("E-Design PKCS7 padding is invalid")
            decoded = decoded[:-padding]
            result["decoded_bytes_sha256"] = _hash(decoded)
            for encoding in ("utf-8", "gb18030"):
                try:
                    text = decoded.decode(encoding)
                    break
                except UnicodeDecodeError:
                    pass
            else:
                raise ValueError("E-Design plaintext is neither UTF-8 nor GB18030")
            result.update(text=text, status="decoded", encoding=encoding)
        except (ValueError, ImportError) as error:
            result["error"] = str(error)
            return result
    else:
        # Opaque unknown wrappers/Base64 blobs must not silently become JS.
        opaque = re.fullmatch(r"[A-Za-z0-9+/=_-]{24,}", stripped)
        if (re.match(r"(?i)^(?:enc(?:rypted)?|base64|aes|edesign)\s*:", stripped)
                or opaque or "\x00" in value):
            result["error"] = "Unrecognized layout script encoding or opaque payload"
            return result
        result.update(text=value, status="plain", encoding="utf-8")
        result["decoded_bytes_sha256"] = _hash(value.encode("utf-8"))
    result["text_sha256"] = _hash(result["text"].encode("utf-8"))
    tokens, _ = _lex(_script_source(result["text"]))
    if not tokens:
        result["status"] = "empty"
    return result


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int


def _lex(source: str) -> tuple[list[_Token], list[dict]]:
    """Tokenize only for static structure; comments and literal braces are inert."""
    tokens, warnings = [], []
    index, length = 0, len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = length if end < 0 else end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                warnings.append({"code": "UNTERMINATED_COMMENT", "message": "Unterminated block comment", "line": source.count("\n", 0, index) + 1})
                break
            index = end + 2
            continue
        if char in "\"'`":
            start, quote = index, char
            index += 1
            while index < length:
                if source[index] == "\\":
                    index += 2
                elif source[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            raw = source[start:index]
            tokens.append(_Token("template" if quote == "`" else "string", raw, start, index))
            if not raw.endswith(quote) or len(raw) == 1:
                warnings.append({"code": "UNTERMINATED_STRING", "message": "Unterminated string literal", "line": source.count("\n", 0, start) + 1})
            if quote == "`" and "${" in raw:
                warnings.append({"code": "DYNAMIC_TEMPLATE", "message": "Template interpolation is not statically evaluated", "line": source.count("\n", 0, start) + 1})
            continue
        # Regular expression bodies can contain braces, slashes and comment text.
        previous = tokens[-1].value if tokens else ""
        after_control = False
        if char == "/" and previous == ")":
            depth = 0
            for cursor in range(len(tokens) - 1, -1, -1):
                if tokens[cursor].value == ")":
                    depth += 1
                elif tokens[cursor].value == "(":
                    depth -= 1
                    if depth == 0:
                        after_control = cursor > 0 and tokens[cursor - 1].value in ("if", "while", "for", "with")
                        break
        if char == "/" and (not tokens or after_control or previous in ("(", "=", ":", ",", "return", "throw", "case", "!", "&&", "||", "[", ";", "=>", "?", "{", "}", "else", "do", "delete", "void", "typeof", "yield", "await", "+", "-", "*", "%", "&", "|", "^", "~", ">", "<")):
            start, in_class, terminated = index, False, False
            if previous == "}":
                warnings.append({"code": "AMBIGUOUS_REGEX", "message": "Slash after a closing brace is treated as an inert regular expression; a complete JavaScript parser is required to distinguish all division contexts", "line": source.count("\n", 0, index) + 1})
            index += 1
            while index < length and source[index] not in "\r\n":
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == "[":
                    in_class = True
                elif source[index] == "]":
                    in_class = False
                elif source[index] == "/" and not in_class:
                    terminated = True
                    index += 1
                    while index < length and source[index].isalpha():
                        index += 1
                    break
                index += 1
            tokens.append(_Token("regex", source[start:index], start, index))
            if not terminated:
                warnings.append({"code": "UNTERMINATED_REGEX", "message": "Unterminated or ambiguous regular expression literal", "line": source.count("\n", 0, start) + 1})
            continue
        match = re.match(r"[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|=>|===|!==|==|!=|&&|\|\||\?\.", source[index:])
        if match:
            value = match.group()
            kind = "id" if re.match(r"[A-Za-z_$]", value) else "punct"
            tokens.append(_Token(kind, value, index, index + len(value)))
            index += len(value)
        else:
            tokens.append(_Token("punct", char, index, index + 1))
            index += 1
    return tokens, warnings


def _literal(token: _Token) -> str | None:
    if token.kind not in ("string", "template") or (token.kind == "template" and "${" in token.value):
        return None
    raw = token.value[1:-1]
    # Decode JS escapes as data; do not use Python/JS eval or unicode_escape.
    def replace(match):
        value = match.group(1)
        if value.startswith("u") and len(value) == 5:
            return chr(int(value[1:], 16))
        if value.startswith("x") and len(value) == 3:
            return chr(int(value[1:], 16))
        return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "\n": ""}.get(value, value)
    return re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r?\n|.)", replace, raw)


def _pairs(tokens: list[_Token]) -> tuple[dict[int, int], bool]:
    pairs, stack, invalid = {}, [], False
    for index, token in enumerate(tokens):
        if token.kind in ("string", "template", "regex"):
            continue
        if token.value in ("(", "{", "["):
            stack.append(index)
        elif token.value in (")", "}", "]"):
            if stack and tokens[stack[-1]].value == {")": "(", "}": "{", "]": "["}[token.value]:
                start = stack.pop()
                pairs[start], pairs[index] = index, start
            else:
                invalid = True
    return pairs, invalid or bool(stack)


def _arguments(tokens, pairs, start, end):
    """Token-index half-open argument ranges, skipping balanced nested groups."""
    ranges, begin, index = [], start, start
    while index < end:
        if tokens[index].value == ",":
            ranges.append((begin, index))
            begin = index + 1
        elif index in pairs and pairs[index] > index:
            index = pairs[index]
        index += 1
    if begin < end:
        ranges.append((begin, end))
    return ranges


def analyze_script(text: str) -> dict:
    """Collect potential static effects and simple local call paths.

    Reachability means a lexical call path exists; it does not mean a branch ran,
    a callback fired, or a request succeeded. Closures, aliases, prototype changes,
    dynamic dispatch and full JavaScript control/data flow are intentionally outside
    this scanner's contract. Original expressions and lines remain reviewable.
    """
    result = {key: [] for key in ("events", "functions", "network_calls", "field_writes", "attribute_changes", "conditions", "warnings")}
    source = _script_source(text)
    tokens, result["warnings"] = _lex(source)
    if not tokens:
        return result
    result["warnings"].append({"code": "STATIC_ANALYSIS_LIMITATION", "message": "Lexical static evidence only: local named calls are followed conservatively; branches, callbacks, aliases and JavaScript runtime semantics are not executed or proven."})
    pairs, invalid = _pairs(tokens)
    if invalid:
        result["warnings"].append({"code": "UNBALANCED_SOURCE", "message": "Unbalanced or unsupported source syntax; findings may be incomplete"})

    def expression(bounds):
        start, end = bounds
        return text[tokens[start].start:tokens[end - 1].end].strip() if start < end else ""

    def line(index):
        return text.count("\n", 0, tokens[index].start) + 1

    def snippet(start, end):
        return text[tokens[start].start:tokens[end].end]

    functions, anonymous_scopes, definition_parens = [], [], set()
    for index, token in enumerate(tokens):
        if token.value != "function":
            continue
        cursor, name = index + 1, None
        if cursor < len(tokens) and tokens[cursor].kind == "id":
            name, cursor = tokens[cursor].value, cursor + 1
        if cursor >= len(tokens) or tokens[cursor].value != "(" or cursor not in pairs:
            continue
        definition_parens.add(cursor)
        body = pairs[cursor] + 1
        if body >= len(tokens) or tokens[body].value != "{" or body not in pairs:
            continue
        if name is None and index >= 2 and tokens[index - 1].value == "=" and tokens[index - 2].kind == "id":
            name = tokens[index - 2].value
        if name:
            functions.append({"name": name, "start": index, "body": body, "end": pairs[body], "line": line(index)})
        else:
            # Promise executors run synchronously when the Promise is constructed.
            # Other anonymous callbacks remain evidence but are not followed as calls.
            promise = index >= 3 and [t.value for t in tokens[index - 3:index]] == ["new", "Promise", "("]
            if not promise:
                anonymous_scopes.append((body, pairs[body]))
    for index, token in enumerate(tokens):
        if token.value != "=>" or index == 0:
            continue
        param = index - 1
        begin = pairs.get(param, param) if tokens[param].value == ")" else param
        if begin >= 2 and tokens[begin - 1].value == "=" and tokens[begin - 2].kind == "id":
            body = index + 1
            if body < len(tokens) and tokens[body].value == "{" and body in pairs:
                functions.append({"name": tokens[begin - 2].value, "start": begin, "body": body, "end": pairs[body], "line": line(begin - 2)})
                continue
        body = index + 1
        if body < len(tokens) and tokens[body].value == "{" and body in pairs:
            anonymous_scopes.append((body, pairs[body]))
        elif body < len(tokens):
            # Concise arrow bodies need expression/control-flow analysis to bind.
            # Keep their findings, but exclude them from an enclosing event path.
            end = body
            while end < len(tokens) and tokens[end].value not in (",", ";", ")", "]", "}"):
                if end in pairs and pairs[end] > end:
                    end = pairs[end]
                end += 1
            anonymous_scopes.append((body - 1, end))
    functions.sort(key=lambda item: item["start"])
    by_name = {}
    for function in functions:
        by_name.setdefault(function["name"], []).append(function)
    if any(len(items) > 1 for items in by_name.values()):
        result["warnings"].append({"code": "AMBIGUOUS_FUNCTION", "message": "Repeated local function names cannot be resolved to runtime bindings; all candidate paths are possible evidence"})

    def owner(index):
        candidates = [f for f in functions if f["body"] < index < f["end"]]
        return min(candidates, key=lambda f: f["end"] - f["body"]) if candidates else None

    calls = []
    excluded = {"if", "for", "while", "switch", "catch", "function", "with"}
    for index, token in enumerate(tokens):
        if token.value != "(" or index not in pairs or index in definition_parens or index == 0:
            continue
        previous = index - 1
        if tokens[previous].kind != "id" or tokens[previous].value in excluded:
            continue
        start = previous
        while start >= 2 and tokens[start - 1].value in (".", "?.") and tokens[start - 2].kind == "id":
            start -= 2
        name = "".join(t.value for t in tokens[start:index])
        calls.append({"name": name, "start": start, "open": index, "end": pairs[index], "args": _arguments(tokens, pairs, index + 1, pairs[index])})

    xhr_names = {
        tokens[index].value
        for index in range(len(tokens) - 4)
        if tokens[index].kind == "id"
        and [t.value for t in tokens[index + 1:index + 5]] == ["=", "new", "XMLHttpRequest", "("]
    }

    for call in calls:
        name, start, end, args = call["name"], call["start"], call["end"], call["args"]
        if name in ("eval", "Function") or (name in ("setTimeout", "setInterval") and args and tokens[args[0][0]].kind in ("string", "template")):
            result["warnings"].append({"code": "DYNAMIC_CODE", "message": "Dynamic code is treated as inert source text and is not expanded", "line": line(start)})
        if name in ("WfForm.changeFieldValue", "WfForm.changeFieldAttr") and args:
            item = {"target": expression(args[0]), "line": line(start), "snippet": snippet(start, end), "function": owner(start)["name"] if owner(start) else None}
            if name.endswith("Value"):
                item["value"] = expression(args[1]) if len(args) > 1 else ""
                result["field_writes"].append(item)
            else:
                item["attribute"] = expression(args[1]) if len(args) > 1 else ""
                result["attribute_changes"].append(item)
        endpoint = None
        network = False
        if name == "fetch" or re.fullmatch(r"(?:\$|jQuery)\.(?:get|post|getJSON)|axios\.(?:get|post|put|patch|delete|head|options)", name):
            network, endpoint = True, args[0] if args else None
        elif name in ("jQuery.ajax", "$.ajax", "axios", "axios.request"):
            network = True
            if args and tokens[args[0][0]].kind in ("string", "template"):
                endpoint = args[0]
            elif args:
                begin, stop = args[0]
                cursor = begin + 1 if tokens[begin].value == "{" else stop
                while cursor < stop - 1:
                    key = _literal(tokens[cursor]) if tokens[cursor].kind == "string" else tokens[cursor].value
                    if key == "url" and tokens[cursor + 1].value == ":":
                        value_start, value_end = cursor + 2, cursor + 2
                        while value_end < stop and tokens[value_end].value not in (",", "}"):
                            if value_end in pairs and pairs[value_end] > value_end:
                                value_end = pairs[value_end]
                            value_end += 1
                        endpoint = value_start, value_end
                        break
                    if cursor in pairs and pairs[cursor] > cursor:
                        cursor = pairs[cursor]
                    cursor += 1
        # Only .open on an explicitly declared XMLHttpRequest variable is a clue.
        elif name.endswith(".open") and name[:-5] in xhr_names:
            network, endpoint = True, args[1] if len(args) > 1 else None
        if network:
            url = _literal(tokens[endpoint[0]]) if endpoint and endpoint[1] - endpoint[0] == 1 else None
            function = owner(start)
            item = {"url": url, "expression": expression(endpoint) if endpoint else "", "line": line(start), "function": function["name"] if function else None, "snippet": snippet(start, end)}
            result["network_calls"].append(item)
            call["network"] = item
            if url is None:
                result["warnings"].append({"code": "DYNAMIC_ENDPOINT", "message": "Network endpoint is not one literal; its runtime URL is unknown", "line": line(start)})

    for index, token in enumerate(tokens[:-1]):
        if token.kind == "id" and token.value in ("if", "while", "switch", "for") and tokens[index + 1].value == "(" and index + 1 in pairs:
            end = pairs[index + 1]
            result["conditions"].append({"kind": token.value, "text": expression((index + 2, end)), "line": line(index), "snippet": snippet(index, end)})

    def inside(call, begin, end, enclosing=None):
        if not begin <= call["start"] < end:
            return False
        if any(begin <= body < call["start"] < stop <= end for body, stop in anonymous_scopes):
            warning = {"code": "UNFOLLOWED_CALLBACK", "message": "An anonymous or concise-arrow callback is recorded as source evidence but is not followed as an enclosing function call", "line": line(call["start"])}
            if warning not in result["warnings"]:
                result["warnings"].append(warning)
            return False
        function = owner(call["start"])
        return function is enclosing or (function is None and enclosing is None)

    for function in functions:
        function["calls"] = list(dict.fromkeys(c["name"] for c in calls if c["name"] in by_name and inside(c, function["body"] + 1, function["end"], function)))
        result["functions"].append({"name": function["name"], "line": function["line"], "calls": function["calls"]})

    for call in calls:
        if not call["name"].startswith("WfForm.") or call["name"].split(".")[-1] not in ("registerCheckEvent", "bindFieldChangeEvent", "bindDetailFieldChangeEvent", "registerAction"):
            continue
        args = call["args"]
        if not args:
            continue
        operation = expression(args[0])
        operation_start, operation_end = args[0]
        operations = list(dict.fromkeys(
            tokens[cursor + 2].value[5:].lower()
            for cursor in range(operation_start, operation_end - 2)
            if tokens[cursor].value == "WfForm" and tokens[cursor + 1].value == "."
            and tokens[cursor + 2].kind == "id"
            and re.fullmatch(r"OPER_[A-Z_]+", tokens[cursor + 2].value)
        ))
        item = {"method": call["name"], "operation": operation, "operations": operations, "line": line(call["start"]), "snippet": snippet(call["start"], call["end"]), "calls": [], "reachable_endpoints": [], "endpoint_paths": []}
        body, body_end, body_owner = None, None, owner(call["start"])
        if len(args) > 1:
            cb_start, cb_end = args[1]
            if cb_end - cb_start == 1 and tokens[cb_start].value in by_name:
                item["calls"] = [tokens[cb_start].value]
            else:
                # Callback braces after its parameter list, never object braces in literals.
                for cursor in range(cb_start, cb_end):
                    if tokens[cursor].value == "{" and cursor in pairs:
                        body, body_end = cursor + 1, pairs[cursor]
                        break
                if body is not None:
                    item["calls"] = list(dict.fromkeys(c["name"] for c in calls if c["name"] in by_name and inside(c, body, body_end, body_owner)))
        paths, seen = [], set()
        if body is not None:
            for candidate in calls:
                if candidate.get("network") and inside(candidate, body, body_end, body_owner):
                    paths.append((candidate["network"], [operation]))
        queue = [(name, [operation, name]) for name in item["calls"]]
        while queue:
            name, path = queue.pop(0)
            if name in seen:
                continue
            seen.add(name)
            for function in by_name.get(name, []):
                for candidate in calls:
                    if candidate.get("network") and inside(candidate, function["body"] + 1, function["end"], function):
                        paths.append((candidate["network"], path))
                queue.extend((target, path + [target]) for target in function["calls"] if target not in seen)
        for network, path in paths:
            if network["url"] is not None:
                if network["url"] not in item["reachable_endpoints"]:
                    item["reachable_endpoints"].append(network["url"])
                item["endpoint_paths"].append({"url": network["url"], "line": network["line"], "path": path})
        if len(args) < 2 or (body is None and not item["calls"]):
            result["warnings"].append({"code": "DYNAMIC_CALLBACK", "message": "Event callback cannot be followed as an inline body or local named function", "line": item["line"]})
        result["events"].append(item)
    return result


def sanitize_script(text: str) -> str:
    """Mask obvious literal secrets while keeping source line numbers stable.

    This deliberately limited redaction is not a general data-loss-prevention
    engine. Computed values are not evaluated, and evidence expressions stay data.
    """
    tokens, _ = _lex(text)
    sensitive = re.compile(r"(?i)^(?:password|passwd|pwd|token|access[_-]?token|refresh[_-]?token|api[_-]?key|secret|client[_-]?secret|authorization)$")
    spans = []
    def redact(value):
        original = text[value.start + 1:value.end - 1]
        replacement = "[REDACTED]" + "".join(char for char in original if char in "\r\n")
        spans.append((value.start + 1, value.end - 1, replacement))

    for index in range(len(tokens) - 2):
        token = tokens[index]
        name = _literal(token) if token.kind == "string" else token.value
        if (name and sensitive.fullmatch(name) and tokens[index + 1].value in ("=", ":")
                and tokens[index + 2].kind in ("string", "template")):
            redact(tokens[index + 2])
        if (name and sensitive.fullmatch(name) and index + 3 < len(tokens)
                and [t.value for t in tokens[index + 1:index + 3]] == ["]", "="]
                and tokens[index + 3].kind in ("string", "template")):
            redact(tokens[index + 3])
        if (name and sensitive.fullmatch(name) and index >= 2
                and tokens[index - 1].value == "("
                and tokens[index - 2].value in ("setRequestHeader", "set", "append")
                and tokens[index + 1].value == ","
                and tokens[index + 2].kind in ("string", "template")):
            redact(tokens[index + 2])
    for start, end, replacement in sorted(set(spans), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
