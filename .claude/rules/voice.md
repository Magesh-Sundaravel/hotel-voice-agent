# Voice output
- Everything the agent says is spoken: no markdown, lists, URLs or emojis in prompts or speech text
- Spoken replies: 1-2 sentences, one question at a time
- Reply in the caller's language (Italian or English); never mix languages in one reply
- Say dates, times and prices the way a person would ("martedi 4 novembre"), never ISO strings
- Latency budget: a tool should answer in under ~1.5 s; slower work needs a filler line or a background job
