# Model triage: setup

When StackVitals' history and the log's signs can't decide whether a pull request's failure came from the change, a model can read the failing step's error lines and the changed file names and give its view. The view is shown beside the verdict in the pull request comment, with its track record; it never changes the verdict or the StackVitals verdict check. At most 3 failures a run are sent, across all pull requests, and a failure the model has already judged is not sent again (its view is kept in the StackVitals comment).

Each provider needs two things: its section in `.github/stackvitals.toml`, and its key as a repository secret passed to the Action as `triage-key`. A private repo's logs are sent only with `allow_private = true`.

## Gemini

Free tier with a Google AI Studio key, no card.

```toml
[ci.triage]
provider = "gemini"
# model = "gemini-3.5-flash-lite"   # the default
```

```yaml
        with:
          triage-key: ${{ secrets.GEMINI_API_KEY }}
```

## OpenAI

Paid; any OpenAI-compatible endpoint by setting url.

```toml
[ci.triage]
provider = "openai"
# model = "gpt-6-luna"   # the default
```

```yaml
        with:
          triage-key: ${{ secrets.OPENAI_API_KEY }}
```

## Anthropic

Paid.

```toml
[ci.triage]
provider = "anthropic"
# model = "claude-haiku-5-5"   # the default
```

```yaml
        with:
          triage-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Mistral

Free experiment tier.

```toml
[ci.triage]
provider = "mistral"
# model = "mistral-small-latest"   # the default
```

```yaml
        with:
          triage-key: ${{ secrets.MISTRAL_API_KEY }}
```

## Groq

Free tier, open models.

```toml
[ci.triage]
provider = "groq"
# model = "openai/gpt-oss-20b"   # the default
```

```yaml
        with:
          triage-key: ${{ secrets.GROQ_API_KEY }}
```

## Any other OpenAI-compatible endpoint

Name any provider above and point `url` at the other endpoint (https), with its model:

```toml
[ci.triage]
provider = "openai"
url = "https://your-endpoint.example.com/v1"
model = "your-model"
```
