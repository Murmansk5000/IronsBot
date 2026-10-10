# Query Matching

`ironsbot.core.text_matching.TextMatchRule` is the shared text-matching template.
Keep each domain's existing normalization function; do not extract words from
sentences or infer a target.

```python
rule = TextMatchRule(normalize_key)
result = rule.select(argument, records, names=lambda row: (row.name, *row.aliases))
```

`MatchResult.kind` is `exact`, `partial`, or `none`. Collect names and aliases in
one call: any complete match excludes all partial matches. Partial matching
uses the entire normalized argument. Empty normalized arguments never match.
Deduplicate domain candidates by their stable IDs before displaying a menu.

Resolve numeric IDs before text. For SQL-backed data, `Getter.resolve_matches`
provides separate exact/partial phases so combined entity queries retain this
priority. `TextMatchRule.contains_pattern` escapes `%`, `_`, and backslashes;
pass `escape="\\"` to SQL LIKE. Existing ignored separators remain ignored.

For fixed commands and configured reply/AI-intent keywords, use
`command_text_matches` (complete normalized text only), not `select` with partial
matching. Name/alias substring searches belong only to explicit query inputs.

An initial query with no candidates returns `None`/an empty `QueryResult` and
releases its pending interaction. Explicit query syntax must not fall through
to AI, recommendations, or generic hints. Permission rejection, unavailable
data, and stale selections from a valid menu still return their own errors.
Bare mentions and ordinary conversational input retain their existing routing.
