"""Aggregate explicit per-response usage; never sum cumulative token counters."""

FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens",
          "reasoning_output_tokens", "total_tokens")


def summarize_tokens(records):
    """Records have already been scoped to project and reporting dates."""
    unique, conflicts = {}, set()
    invalid = 0
    for owner, record in records:
        usage = record.get("usage")
        response = record.get("response_id")
        if not isinstance(response, str) or not response or not isinstance(usage, dict):
            invalid += 1
            continue
        values = {key: usage.get(key) for key in FIELDS}
        if (any(type(value) is not int or value < 0 for value in values.values())
                or values["cached_input_tokens"] > values["input_tokens"]
                or values["reasoning_output_tokens"] > values["output_tokens"]
                or values["total_tokens"] != values["input_tokens"] + values["output_tokens"]):
            invalid += 1
            continue
        key = (owner, response)
        if key in unique and unique[key][0] != values:
            conflicts.add(key)
        elif key not in unique:
            unique[key] = (values, record["timestamp"])
    accepted = [value for key, value in unique.items() if key not in conflicts]
    stamps = [stamp for _, stamp in accepted]
    return {
        "available": bool(accepted), "partial": True,
        "responses": len(accepted),
        **{key: sum(values[key] for values, _ in accepted) if accepted else None
           for key in FIELDS},
        "first_event": min(stamps).isoformat() if stamps else None,
        "last_event": max(stamps).isoformat() if stamps else None,
        "invalid_records": invalid, "conflicting_responses": len(conflicts),
        "definition": "Input plus output tokens from explicit per-response records. "
                      "Cached input is a subset of input; reasoning is a subset of output.",
        "coverage_note": "Partial local records; first and last events do not prove "
                         "continuous coverage. Not a billing amount, productivity score, "
                         "or time-saved estimate.",
    }
