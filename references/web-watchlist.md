# Web gap watchlist

These important organizations did not expose a verified stable feed during the 2026-07-15 audit. They are optional gap checks after deterministic feed collection; they must not become unbounded daily scraping targets.

## AI labs and model providers

- Anthropic News — https://www.anthropic.com/news
- Meta AI Blog — https://ai.meta.com/blog/
- Mistral AI News — https://mistral.ai/news
- Cohere Research — https://cohere.com/research
- xAI News — https://x.ai/news
- DeepSeek — https://github.com/deepseek-ai
- Qwen — https://qwenlm.github.io/

## Robotics and embodied AI

- Boston Dynamics Blog — https://bostondynamics.com/blog/
- Figure — https://www.figure.ai/news
- Physical Intelligence — https://www.physicalintelligence.company/blog
- Skild AI — https://www.skild.ai/blog
- 1X — https://www.1x.tech/discover
- Unitree — https://www.unitree.com/
- Agility Robotics — https://agilityrobotics.com/news

## Developer and research ecosystems

- LangChain Blog — https://www.langchain.com/blog
- PyTorch Blog — https://pytorch.org/blog/
- Google Cloud AI & ML — https://cloud.google.com/blog/products/ai-machine-learning
- Weights & Biases Fully Connected — https://wandb.ai/fully-connected
- Stanford HAI News — https://hai.stanford.edu/news
- MIT CSAIL News — https://www.csail.mit.edu/news

## Gap-check rules

1. Run only when the feed manifest has an obvious coverage gap or a major event is suspected.
2. Prefer `web_search` restricted to the official domain, then open the original page.
3. Do not infer a publication date from search ranking. Require a visible or structured date.
4. Do not add a story solely because an organization is prominent.
5. Cache and deduplicate gap results against the SQLite manifest.
6. A gap-check failure never aborts the deterministic collector.
