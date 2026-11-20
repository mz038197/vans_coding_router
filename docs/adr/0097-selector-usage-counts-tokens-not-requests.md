# Selector Usage counts tokens, not requests

Every `vcr-auto` chat or Responses call under Automatic Models, or on a Personal API Key, may first ask the vcr-auto Selector which Auto Tier it needs. That question costs tokens. Until now it was recorded nowhere, so Token Usage under-reported what a student's prompts cost.

A Selector reply that reports tokens now adds one Token Usage record of its own, a Selector Usage. It is charged to the user, Class, and Class Session of the call that asked it. It counts toward the token totals and not toward the request count, so the request count still means how many calls the student made. It is recorded even when that call's walk then produces no output, and even when the answer could not be read, because the tokens were already spent. A question that timed out, failed upstream, or was answered from selection memory adds nothing. It is never a Prompt Log: a Prompt Log for every chat question would flood the teacher's list with the router's own bookkeeping.

The Portal usage page still shows one total per student. The record is marked, so a separate Selector column can be added later without new data.

## Considered Options

- **Record nothing**: rejected. The selector runs on most Automatic Models chat calls, so the usage page was missing a steady cost.
- **One record that also counts as a request**: rejected. Every chat would count twice, and the request count would no longer match what the student did.
- **Add the selector tokens onto the chat call's record**: rejected. That record names the Model ID that produced output, not the selector, and a walk that produced no output writes no record, so the selector's spend would disappear with it.
- **A Prompt Log for each selector question**: rejected. The teacher reads Prompt Logs to see what students asked, not how the router sorted it.
