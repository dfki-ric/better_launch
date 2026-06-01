import fnmatch


def glob_dict(data: dict, pattern: str, invert: bool = False, strip: bool = True) -> dict:
    """Filter a nested dict by a glob pattern.

    Keys may contain slashes which are treated as path separators.

    This function supports wildcards both in dict keys and the provided pattern. * will match a single key part or skip a single pattern part. ** will consider the entire remaining branch as matching.

    **Note** that this function is destructive and will prune parts of the provided dictionary not matching pattern. Use `copy.deepcopy` if you want to keep your input dict untouched.

    Parameters
    ----------
    data : dict
        The input dictionary. Non-matching parts will be removed.
    pattern : str
        A glob-style pattern to select parts of the dictionary to keep.
    invert : bool, optional
        If True, only retain branches that do *not* match the provided pattern.
    strip : bool, optional
        If True, the matched qualifier prefix is removed from the keys of the returned dict.

    Returns
    -------
    dict
        The pruned input dict.
    """
    if not pattern or pattern in ("*", "**"):
        if invert:
            return {}
        return data

    def match(sub: dict, pat: list[str]) -> bool:
        """Recursively filter sub to only keep keys matching pat"""
        if not isinstance(sub, dict):
            # Leaf, valid only if pattern was fully consumed
            return not pat

        bad_keys = []
        renames = {}
        
        for key in list(sub.keys()):
            key_parts = [p for p in key.split("/") if p]
            survived, stripped_key = match_key_parts(sub, key, key_parts, pat)

            if invert:
                survived = not survived
            
            if not survived:
                bad_keys.append(key)
            elif strip and stripped_key != key:
                renames[key] = stripped_key
            
        for key in bad_keys:
            del sub[key]
        
        # Strip the matched qualifiers if desired
        for old, new in renames.items():
            sub[new] = sub.pop(old)
        
        # Return True if content remaining
        return bool(sub)

    def match_key_parts(
        sub: dict, key: str, key_parts: list[str], pat: list[str]
    ) -> tuple[bool, str]:
        """Match key_parts against pat, then recurse into children with remaining pattern."""
        if not pat:
            # Pattern exhausted but key remains - no match
            return False, key
        
        # Consume key_parts against pat elements one by one
        remaining_key, remaining_pat = consume(key_parts, pat)
        if remaining_pat is None:
            return False, key
        
        # Pattern fully consumed: keep this node entirely
        if not remaining_pat and not remaining_key:
            return True, ""
        
        # Pattern still has elements: recurse into children
        child = sub[key]
        if not isinstance(child, dict):
            # Can't go deeper but pattern isn't done
            return False, key
        
        # Pat exhausted but key had extra parts (e.g. key "a/b", pattern "a"),
        # this is still a match
        if not remaining_pat and remaining_key:
            stripped = "/".join(remaining_key) if strip else key
            return True, stripped
        
        survived = match(child, remaining_pat)
        return survived, key

    def consume(key_parts: list[str], pat: list[str]) -> tuple[list[str], list[str]]:
        """Step through key_parts and pat, trying to match the two, then return what remains."""
        key_idx, pat_idx = 0, 0
        while key_idx < len(key_parts) and pat_idx < len(pat):
            sub_pat = pat[pat_idx]
            sub_key = key_parts[key_idx]

            if sub_pat == "**":
                # Big wildcard pattern will consume the remaining key parts
                return ([], pat[pat_idx + 1 :])
            elif sub_key == "*" or fnmatch.fnmatch(sub_key, sub_pat):
                # fnmatch also handles the * sub-pattern
                key_idx += 1
                pat_idx += 1
            elif sub_key == "**":
                # Big wildcard key will consume the remaining pattern
                return ([], [])
            else:
                # Mismatch
                return (None, None)

        # Either the pattern parts or the key parts were exhausted
        return (key_parts[key_idx:], pat[pat_idx:])

    match(data, [p for p in pattern.split("/") if p])
    return data


def deep_merge(base: dict, override: dict) -> dict:
    """Merge a (nested) override dict into a (nested) base dict. 

    After this operation the entirety of override will be part of base. All values will be assigned without any copies. This operation will alter the provided base dict. Use copy.deepcopy if you don't want this.

    Parameters
    ----------
    base : dict
        The dict into which the override will be merged.
    override : dict
        The override to merge into base.

    Returns
    -------
    dict
        The merged dict, which is the modified base dict.
    """
    result = dict(base)

    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v

    return result


def merge_and_explode(*dicts: dict) -> dict:
    """Recursively merge any number of nested dicts.

    All keys (including those of nested dicts) must be strings. Compound keys (e.g. "a/b") are exploded into nested dicts first. Later dicts win on key conflicts at leaf level.

    Parameters:
    -----------
    dicts: dict
        The dictionaries to merge.

    Returns
    -------
    dict
        A dict which is the result of exploding and merging all input dicts.
    """

    # TODO should also handle wildcard dicts
    def explode(d: dict) -> dict:
        """Expand all compound keys into nested dicts."""
        result = {}

        for key, value in d.items():
            parts = [p for p in key.split("/") if p]
            child = explode(value) if isinstance(value, dict) else value
            top = parts[0]

            # Build nested dict from innermost out
            for part in reversed(parts[1:]):
                child = {part: child}

            if (
                top in result
                and isinstance(result[top], dict)
                and isinstance(child, dict)
            ):
                result[top] = merge_and_explode(result[top], child)
            else:
                result[top] = child

        return result

    exploded = [explode(d) for d in dicts]
    merged = exploded[0]
    for nxt in exploded[1:]:
        merged = deep_merge(merged, nxt)

    return merged


# FOR TESTING
# TODO turn into proper CI test
if __name__ == "__main__":
    import copy

    data = {
        "**": {
            "no": "dstar",
            "test": "dstar",
        },
        "a": {
            "b": {
                "c": "hit",
                "d": "excl",
            },
            "x": "excl",
        },
        "a/b": {
            "c": "hit2",
            "d": "excl",
        },
        "docs": {
            "readme": "hit",
            "guide": "hit",
        },
        "logs": {
            "2024": {
                "jan": "hit",
                "feb": "hit",
            }
        },
        "other": "excl",
    }

    cases = [
        (
            "a",
            "get all of a, but also a/b",
            {
                "**": {
                    "no": "dstar",
                    "test": "dstar",
                },
                "a": {"b": {"c": "hit", "d": "excl"}, "x": "excl"},
                "a/b": {"c": "hit2", "d": "excl"},
            },
        ),
        (
            "a/b/c",
            "exact match + sibling exclusion",
            {
                "**": {
                    "no": "dstar",
                    "test": "dstar",
                },
                "a": {"b": {"c": "hit"}},
                "a/b": {"c": "hit2"},
            },
        ),
        (
            "a/b/*",
            "terminal wildcard",
            {
                "**": {
                    "no": "dstar",
                    "test": "dstar",
                },
                "a": {"b": {"c": "hit", "d": "excl"}},
                "a/b": {"c": "hit2", "d": "excl"},
            },
        ),
        (
            "logs/**",
            "double-star matches all descendants",
            {
                "**": {
                    "no": "dstar",
                    "test": "dstar",
                },
                "logs": {"2024": {"jan": "hit", "feb": "hit"}},
            },
        ),
        (
            "*/b/c",
            "star with specific child",
            {
                "a": {"b": {"c": "hit"}},
                "a/b": {"c": "hit2"},
            },
        ),
        (
            "**/test",
            "double-star with specific child",
            {
                "**": {
                    "test": "dstar",
                }
            },
        ),
        (
            "z",
            "only wildcards for unknown key",
            {
                "**": {
                    "no": "dstar",
                    "test": "dstar",
                }
            },
        ),
    ]

    passed = 0
    failed = 0
    for pattern, desc, expected in cases:
        result = glob_dict(copy.deepcopy(data), pattern)
        ok = result == expected
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] ({pattern})  {desc}")
        if not ok:
            print(f"       expected: {expected}")
            print(f"       got:      {result}")
            failed += 1
        else:
            passed += 1

    print(f"\n{passed}/{passed + failed} passed")
    print("\nmerge_dicts:", merge_and_explode(data))
