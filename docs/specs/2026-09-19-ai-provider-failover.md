# AI Provider Failover

Status: implemented

## Contract

- `[ai].provider_order` is the authoritative provider priority.
- `[ai.providers.<alias>].models` is the model priority within one provider.
- Each provider has its own OpenAI-compatible `base_url`, model list, thinking
  setting, and deployment key.
- Secrets are read only from `AI_KEY_<UPPERCASE_ALIAS>`.
- A missing key leaves that provider inactive. At least one configured provider
  is required before AI commands are exposed.
- A declared provider not listed in `provider_order`, an unknown environment
  provider, a TOML `api_key`, or the retired `AI_KEY` variable fails strict
  configuration loading.

## Request Order

Requests iterate providers, then models. Transport failures and API failures
advance to the next candidate. HTTP 401/403 skips the remaining models under
that provider because they share the same rejected credential. A successful
response stops the sequence. The final structured failure identifies the last
provider and model attempted without logging any key.

## Migration

Remove these former `[ai]` fields:

- `base_url`
- `model`
- `fallback_models`
- `thinking`

Replace them with one or more `[ai.providers.<alias>]` tables and set
`provider_order`. Replace `AI_KEY` with one `AI_KEY_<UPPERCASE_ALIAS>` per
provider. README, Docker documentation, `.env.example`, `config.example.toml`,
and the Unraid template use only this target schema.
