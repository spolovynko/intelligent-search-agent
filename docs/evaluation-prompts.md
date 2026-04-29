# Companion Evaluation Prompts

Use these prompts after retrieval, routing, or UI changes. The expected mode is
the SSE `findings.mode` value from `/v1/chat/companion/stream`.

| Prompt | Expected mode | What to check |
| --- | --- | --- |
| Show me images of the Belgian Revolution | `asset_table` | Image table appears with Show buttons. |
| Find maps or visuals related to Antwerp history | `asset_table` | Image table contains visual/map-like matches. |
| What happened during the Belgian Revolution? | `chat` | Answer is prose in chat with document source chips. |
| What sources discuss Belgian patriotism in 1830? | `chat` | Answer cites PDF/document refs and no image panel appears. |
| Explain the Belgian Revolution and show related images | `mixed` | Prose answer streams, source chips appear, and image table appears. |
| Show paintings connected to Belgian independence | `asset_table` | Route sets an image/asset intent and table appears. |
| Give me a short summary of Antwerp in Belgian history | `chat` | Document retrieval only, no image table. |
| Find images and sources about Belgian patriotism in 1830 | `mixed` | Both images and documents are retrieved. |
| Hello, what can you do? | `chat` | No corpus search is required; answer stays conversational. |
| Can you show what happened during the Belgian Revolution? | `chat` | The word "show" alone must not trigger image mode. |
| Only paintings, after an image request | `asset_table` | The assistant reuses the previous image topic and filters to paintings. |
| Show sources too, after an image request | `mixed` | The assistant reuses the previous image topic and adds PDF evidence. |

Manual smoke command:

```powershell
$body = @{ question = 'Explain the Belgian Revolution and show related images' } | ConvertTo-Json -Compress
(Invoke-WebRequest -Uri 'http://localhost:8000/v1/chat/companion/stream' -Method POST -ContentType 'application/json' -Body $body -UseBasicParsing -TimeoutSec 180).Content
```

Manual UI QA:

1. Ask `Show me images of the Belgian Revolution`.
2. Click a `Show` button and verify the image preview modal opens.
3. Ask `Only paintings` and verify the table stays on Belgian Revolution images but filters to paintings.
4. Ask `Show sources too` and verify the answer becomes mixed, with image findings and source chips.
5. Click a source chip and verify the source preview opens with a PDF iframe and retrieved excerpt.
