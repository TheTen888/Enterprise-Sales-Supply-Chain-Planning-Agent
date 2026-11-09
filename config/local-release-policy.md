# Local release qualification

For the explicitly requested shift-left acceptance stage, `QUALIFICATION_SCOPE=local_release` selects a local-release gate. Deployment qualification requires real AgentCore HTTP health/invocation/schema/auth tests plus static Dockerfile validation. These checks do not claim a container was built or that AWS was deployed. The stricter cloud-production profile continues to require actual container and AWS runtime evidence.

The label-review gate combines the user's approved existing authored expectations with a different real OpenAI judge model. This is independent model consistency review against project-authored business rules, not an independent expert signature. Initial rejected judge results are retained alongside the corrected review contract.

The real-model gate requires all inference-eligible cases to use the real model and semantic retrieval, with no mock fallback, passing business assertions and remotely retrievable LangSmith traces. The malformed-quarter case deliberately invokes no model and has its own traced validation result. Real-model failure records are preserved; tests are not relabeled to manufacture a pass.

`.env` is loaded privately, aliases `LANGCHAIN_API_KEY`/`LANGCHAIN_PROJECT` map to LangSmith configuration, and the file is excluded from Git and Docker build context. Weight downloads are pinned to repository revisions under ignored runtime storage. Neither keys nor weights enter the source tree's public artifacts.

Memory abstention uses a TinyBERT-specific cross-encoder score cutoff of -5 after hybrid candidate retrieval. Development checks included shipping/FOB and ECN positives plus unrelated warranty, birthday and certification queries. A cosine candidate alone cannot establish evidence. This cutoff is not transferable to an arbitrary reranker without new calibration, and a broad/ambiguous query may intentionally abstain.
