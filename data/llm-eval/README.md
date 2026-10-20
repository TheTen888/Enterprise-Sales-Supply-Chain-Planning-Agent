# Synthetic model evaluation inputs

`development.json` contains four development cases. `holdout.json` contains 16 separately stored acceptance cases. Expected decisions and supporting citation IDs are outside the inference input. Cases cover paraphrases, Chinese evidence, capacity conflicts, missing cost/evidence, other customers, old/deleted/design-mismatched documents, prompt injection and unsupported requests.

These are provisional synthetic expectations authored separately from the candidate's responses. Independent human review is pending. The set is small, has not been validated against real business outcomes and is not a statistically representative model benchmark. No real model has been evaluated on it in this release.

`contract-responses.json` contains deliberately authored fake model responses for the existing quote fixture. The fake SDK selects known scripted branches; it is neither an LLM nor an independent judge. Those responses test adapter wiring, tool-result IDs, parsing, source checks and numerical safeguards. They never become measured model accuracy or token throughput.

The offline runner scores the frozen `RulesAssessor` against the two annotated sets. Candidate model scores remain `null` with `not_measured` status. Rules task success here is about the narrow evidence-assessment policy; it is not the overall success rate of the original ETL/RAG/quote workflow.

`gate.json` records provisional qualification criteria for a future local shadow pilot. Real model evidence and independently reviewed labels are required. Passing fake SDK contracts cannot open that gate. A future real run must freeze the prompt, rules, data hashes and criteria before inspecting acceptance results; cases used for tuning must no longer be described as unseen holdout data.
