from typing import Any
import re


class TomlReader:
    def __init__(self, text: str | list[str]):
        """TOML parser with better comment handling compared to existing ones. 
        
        Noticably, this parser will preserve and associate comments that appear *before* the key they are describing. Comments appear in the same dict as their associated key under the key `__comment_<key>__`. In addition, a comment at the start of the file will be retained as well. This root comment has the key `__comment__`.

        Some standard features are not supported right now:
        - octal integers (0oXXXX)
        - dates and times remain strings
        - arrays of tables ([[my-aot]])

        The following non-standard features are supported:
        - write `key = <base-type>` to set its value to the corresponding class. Base types are int, float, str, bool, list, dict.

        Parameters
        ----------
        text : str | list[str]
            The toml content to be parsed.
        """
        if isinstance(text, list):
            self.lines = text
        else:
            self.lines = text.splitlines()
        
        self.data: dict[str, Any] = {}
        self.current_table = self.data
        self.table_path: list[str] = []

    def parse(self) -> dict[str, Any]:
        """Parse TOML text and return a dictionary."""
        i = 0
        pending_comment: str = None
        root_comment: str = None
        root_comment_done = False

        while i < len(self.lines):
            line = self.lines[i].strip()

            # Empty line resets pending comment (and marks end of root comment section)
            if not line:
                if pending_comment and not root_comment_done and not self.table_path:
                    root_comment = pending_comment
                    root_comment_done = True
                pending_comment = None
                i += 1
                continue

            # Comment line
            if line.startswith("#"):
                comment_text = line[1:].strip()
                if pending_comment is None:
                    pending_comment = comment_text
                else:
                    pending_comment += "\n" + comment_text
                i += 1
                continue

            # Table header
            if line.startswith("["):
                if line.startswith("[["):
                    raise NotImplementedError("Array of tables [[...]] not supported")

                match = re.match(r"\[([^\]]+)\]", line)
                if not match:
                    raise ValueError(f"Invalid table header: {line}")

                table_name = match.group(1).strip()

                # Save root comment if we haven't yet and no table has been set
                if not root_comment_done and not self.table_path and pending_comment:
                    root_comment = pending_comment
                    root_comment_done = True
                    pending_comment = None

                self._set_table(table_name)

                if pending_comment:
                    self.current_table["__comment__"] = pending_comment
                    pending_comment = None

                i += 1
                continue

            # Key-value pair (check if line contains = but isn't inside a comment)
            if "=" in line and not line.startswith("#"):
                key, value, lines_consumed = self._parse_key_value(line, i)
                self._set_dotted_key(key, value)

                # Associate comment with key
                if pending_comment:
                    # For dotted keys, store comment with the final key
                    if "." in key:
                        parts = key.split(".")
                        final_key = parts[-1]
                        target = self._navigate_to_parent(parts[:-1])
                        target[f"__comment_{final_key}__"] = pending_comment
                    else:
                        self.current_table[f"__comment_{key}__"] = pending_comment
                    pending_comment = None

                i += lines_consumed
                continue

            raise ValueError(f"Unexpected line: {line}")

        # Set root comment at the end
        if root_comment:
            self.data["__comment__"] = root_comment

        return self.data

    def _set_table(self, table_path: str):
        """Set the current table based on dot-separated path."""
        parts = [p.strip().strip('"').strip("'") for p in table_path.split(".")]
        self.table_path = parts
        self.current_table = self.data

        for part in parts:
            if part not in self.current_table:
                self.current_table[part] = {}
            self.current_table = self.current_table[part]

    def _set_dotted_key(self, key: str, value: Any):
        """Set a value using dotted key notation."""
        if "." not in key:
            self.current_table[key] = value
            return

        parts = key.split(".")
        target = self.current_table

        for part in parts[:-1]:
            part = part.strip().strip('"').strip("'")
            if part not in target:
                target[part] = {}
            target = target[part]

        final_key = parts[-1].strip().strip('"').strip("'")
        target[final_key] = value

    def _navigate_to_parent(self, parts: list[str]) -> dict[str, Any]:
        """Navigate to parent table for dotted key."""
        target = self.current_table
        for part in parts:
            part = part.strip().strip('"').strip("'")
            if part not in target:
                target[part] = {}
            target = target[part]
        return target

    def _parse_key_value(self, line: str, line_idx: int) -> tuple[str, Any, int]:
        """Parse a key-value pair, potentially spanning multiple lines."""
        key, _, value_str = line.partition("=")
        key = key.strip()
        value_str = value_str.strip()

        lines_consumed = 1

        # Handle multi-line strings first
        if value_str.startswith('"""') or value_str.startswith("'''"):
            quote = '"""' if value_str.startswith('"""') else "'''"
            # Check if string closes on same line
            if value_str.count(quote) >= 2:
                # Closed on same line
                pass
            else:
                # Multi-line string - read until closing quotes
                full_value = value_str
                idx = line_idx + 1
                while idx < len(self.lines):
                    full_value += "\n" + self.lines[idx]
                    lines_consumed += 1
                    if quote in self.lines[idx]:
                        break
                    idx += 1
                value_str = full_value
        # Check if we need to read multiple lines for arrays or inline dicts
        elif (
            value_str.startswith("[") or value_str.startswith("{")
        ) and not self._is_closed(value_str):
            full_value = value_str
            idx = line_idx + 1
            while idx < len(self.lines) and not self._is_closed(full_value):
                full_value += " " + self.lines[idx].strip()
                lines_consumed += 1
                idx += 1
            value_str = full_value

        value_str = self._remove_inline_comment(value_str)
        value = self._parse_value(value_str)
        return key, value, lines_consumed

    def _is_closed(self, s: str) -> bool:
        """Check if brackets/braces are balanced."""
        stack = []
        in_string = False
        string_char = None
        i = 0

        while i < len(s):
            char = s[i]

            if char in ('"', "'") and (i == 0 or s[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
            elif not in_string:
                if char in "[{":
                    stack.append(char)
                elif char == "]":
                    if not stack or stack[-1] != "[":
                        return False
                    stack.pop()
                elif char == "}":
                    if not stack or stack[-1] != "{":
                        return False
                    stack.pop()
            i += 1

        return len(stack) == 0

    def _remove_inline_comment(self, value_str: str) -> str:
        """Remove inline comments, respecting strings."""
        in_string = False
        string_char = None
        i = 0

        while i < len(value_str):
            char = value_str[i]

            # Handle triple-quoted strings
            if i + 2 < len(value_str):
                triple = value_str[i : i + 3]
                if triple in ('"""', "'''"):
                    if not in_string:
                        in_string = True
                        string_char = triple
                        i += 3
                        continue
                    elif string_char == triple:
                        in_string = False
                        string_char = None
                        i += 3
                        continue

            if char in ('"', "'") and (i == 0 or value_str[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char and len(string_char) == 1:
                    in_string = False
                    string_char = None
            elif char == "#" and not in_string:
                return value_str[:i].strip()

            i += 1

        return value_str.strip()

    def _parse_value(self, value_str: str) -> Any:
        """Parse a TOML value."""
        value_str = value_str.strip()

        # Type annotations: key = int, key = str, etc.
        type_map = {
            'int': int,
            'float': float,
            'str': str,
            'bool': bool,
            'list': list,
            'dict': dict,
        }
        if value_str in type_map:
            return type_map[value_str]

        # Multi-line basic string
        if value_str.startswith('"""') and value_str.endswith('"""'):
            content = value_str[3:-3]
            if content.startswith("\n"):
                content = content[1:]
            return self._process_escapes(content)

        # Multi-line literal string
        if value_str.startswith("'''") and value_str.endswith("'''"):
            content = value_str[3:-3]
            if content.startswith("\n"):
                content = content[1:]
            return content

        # Basic string
        if value_str.startswith('"') and value_str.endswith('"'):
            return self._process_escapes(value_str[1:-1])

        # Literal string
        if value_str.startswith("'") and value_str.endswith("'"):
            return value_str[1:-1]

        # Boolean
        if value_str.lower() == "true":
            return True
        if value_str.lower() == "false":
            return False

        # Special float values
        if value_str in ("inf", "+inf"):
            return float("inf")
        if value_str == "-inf":
            return float("-inf")
        if value_str in ("nan", "+nan", "-nan"):
            return float("nan")

        # Inline dict
        if value_str.startswith("{") and value_str.endswith("}"):
            return self._parse_inline_dict(value_str[1:-1])

        # Array
        if value_str.startswith("[") and value_str.endswith("]"):
            return self._parse_array(value_str[1:-1])

        # Hexadecimal integer
        if value_str.startswith("0x"):
            return int(value_str, 16)

        # Binary integer
        if value_str.startswith("0b"):
            return int(value_str, 2)

        # Octal integer
        if value_str.startswith("0o"):
            return int(value_str, 8)

        # Number with underscores
        value_str_clean = value_str.replace("_", "")
        try:
            if "." in value_str_clean or "e" in value_str_clean.lower():
                return float(value_str_clean)
            return int(value_str_clean)
        except ValueError:
            pass

        return value_str

    def _process_escapes(self, s: str) -> str:
        """Process escape sequences in strings."""
        result = []
        i = 0
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s):
                next_char = s[i + 1]
                if next_char == "n":
                    result.append("\n")
                    i += 2
                elif next_char == "t":
                    result.append("\t")
                    i += 2
                elif next_char == "r":
                    result.append("\r")
                    i += 2
                elif next_char == "\\":
                    result.append("\\")
                    i += 2
                elif next_char == '"':
                    result.append('"')
                    i += 2
                elif next_char == "b":
                    result.append("\b")
                    i += 2
                elif next_char == "f":
                    result.append("\f")
                    i += 2
                elif next_char == "u" and i + 5 < len(s):
                    hex_code = s[i + 2 : i + 6]
                    try:
                        result.append(chr(int(hex_code, 16)))
                        i += 6
                    except ValueError:
                        result.append(s[i])
                        i += 1
                elif next_char == "U" and i + 9 < len(s):
                    hex_code = s[i + 2 : i + 10]
                    try:
                        result.append(chr(int(hex_code, 16)))
                        i += 10
                    except ValueError:
                        result.append(s[i])
                        i += 1
                else:
                    result.append(s[i])
                    i += 1
            else:
                result.append(s[i])
                i += 1
        return "".join(result)

    def _parse_inline_dict(self, dict_str: str) -> dict[str, Any]:
        """Parse an inline TOML dictionary."""
        dict_str = dict_str.strip()
        if not dict_str:
            return {}

        result = {}
        current = ""
        depth = 0
        in_string = False
        string_char = None

        for char in dict_str:
            if char in ('"', "'") and not in_string:
                in_string = True
                string_char = char
                current += char
            elif char == string_char and in_string:
                in_string = False
                string_char = None
                current += char
            elif char in "[{" and not in_string:
                depth += 1
                current += char
            elif char in "]}" and not in_string:
                depth -= 1
                current += char
            elif char == "," and depth == 0 and not in_string:
                if current.strip() and "=" in current:
                    key, value = self._parse_inline_dict_pair(current.strip())
                    result[key] = value
                current = ""
            else:
                current += char

        if current.strip() and "=" in current:
            key, value = self._parse_inline_dict_pair(current.strip())
            result[key] = value

        return result

    def _parse_inline_dict_pair(self, pair_str: str) -> tuple[str, Any]:
        """Parse a key-value pair from an inline dict."""
        key, _, value_str = pair_str.partition("=")
        key = key.strip().strip('"').strip("'")
        value_str = value_str.strip()
        return key, self._parse_value(value_str)

    def _parse_array(self, array_str: str) -> list[Any]:
        """Parse a TOML array."""
        array_str = array_str.strip()
        if not array_str:
            return []

        elements = []
        current = ""
        depth = 0
        in_string = False
        string_char = None

        for char in array_str:
            if char in ('"', "'") and not in_string:
                in_string = True
                string_char = char
                current += char
            elif char == string_char and in_string:
                in_string = False
                string_char = None
                current += char
            elif char == "[" and not in_string:
                depth += 1
                current += char
            elif char == "]" and not in_string:
                depth -= 1
                current += char
            elif char == "{" and not in_string:
                depth += 1
                current += char
            elif char == "}" and not in_string:
                depth -= 1
                current += char
            elif char == "," and depth == 0 and not in_string:
                if current.strip():
                    elements.append(self._parse_value(current.strip()))
                current = ""
            else:
                current += char

        if current.strip():
            elements.append(self._parse_value(current.strip()))

        return elements


def loads(text: str) -> dict[str, Any]:
    """Parse TOML text and return a dictionary."""
    reader = TomlReader(text)
    return reader.parse()


def load(path: str) -> dict[str, Any]:
    """Read the contents of a TOML file and parse them."""
    with open(path) as f:
        content = f.read()

    return loads(content)


# Example usage
if __name__ == "__main__":
    toml_text = """# This is the root comment
# It spans multiple lines

# Database configuration
[database]
host = "localhost"
port = 5432

# Connection settings
timeout = 30
config = {retry = 3, delay = 100, }

[server]
# Server address
address = "0.0.0.0"
ports = [8080, 8081, 8082, ]
multi_line = [
    1, 2, 3,
    4, 5, 6,
]

# Nested config using dotted keys
[server.logging]
server.logging.level = "info"
server.logging.file = "/var/log/app.log"

[numbers]
hex = 0xDEADBEEF
binary = 0b11010110
with_underscores = 1_000_000
special = inf
neg_inf = -inf
not_a_num = nan

[strings]
basic = "Hello\\nWorld"
literal = 'C:\\Users\\path'
unicode = "Emoji: \\u2764"
multiline = \"""
This is a
multi-line string\"""
multiline_literal = '''
No escapes here: \\n stays literal'''

[nested]
inline = {
    name = "prod",
    settings = {debug = false, level = 5, },
}

[types]
# Type annotations - values are set to the type itself
my_int_type = int
my_float_type = float
my_str_type = str
my_bool_type = bool
my_list_type = list
my_dict_type = dict
"""
    import json

    result = loads(toml_text)
    print(json.dumps(result, indent=2, default=str))
