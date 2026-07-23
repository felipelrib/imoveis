# Analyze this project and check how the workflows work, both ...

**Data/Hora:** 2026-07-20 21:49:23 | **Chat ID:** `befaa6bc-5e91-4864-8760-015ef4a0dce4`

---

### 👤 User (21:49:23)

Analyze this project and check how the workflows work, both for CI and development using Cline and all rules and skills associated to Cline. Check https://docs.cline.bot/customization/cline-rules and other pages from docs to see how Cline works and consider I'll be using it for this and other project's development. I want to have the best AI harness for development, both for accomplishing tasks from Linear and also validating the tasks were successfully implemented, verified, all CI works and documentations and Linear were updated accordingly. Also I want to clean up files in the repo and only leave files/docs/rules that make sense to be in the project other than in Linear. Consider I have to update README accordingly always to say how the project works and its features, how each feature was implemented (and this could be more internal doc living within the repo and not necessarily inside the main README, but having links in there), the architecture behind it, the decisions and whys. Consider that the development is fully made through Cline by using a strongest model (DeepSeek v4 pro) for planning and a lower context/cheaper model for implementing the plan. Considering all this, prepare me a full prompt so I can use Claude Opus to do the hard work here, I just need the prompt and all the context you can give me in the prompt so I can start another agent to do what I need

<ADDITIONAL_METADATA>
The current local time is: 2026-07-20T18:49:23-03:00.

The user's current state is as follows:
Active Document: /home/felipe/workfolder/imoveis/README.md (LANGUAGE_MARKDOWN)
Cursor is on line: 1
Other open documents:
- /home/felipe/workfolder/imoveis/README.md (LANGUAGE_MARKDOWN)
</ADDITIONAL_METADATA>
<USER_SETTINGS_CHANGE>
The user changed setting `Model Selection` from None to Gemini 3.1 Pro (High). No need to comment on this change if the user doesn't ask about it. If reporting what model you are, please use a human readable name instead of the exact string.
</USER_SETTINGS_CHANGE>

---

### 👤 Assistant (21:50:18)

I have analyzed the project structure, the current `README.md`, and all your custom rules and skills within `.clinerules/` and `.cline/`. I also fetched the latest Cline documentation regarding how rules and customizations work to ensure the architecture is sound.

I've crafted a comprehensive prompt for Claude Opus that contains all this context and outlines your exact goals:
1. Setting up the optimal AI harness utilizing the "Planner (DeepSeek v4 pro) + Implementer (cheap model)" paradigm.
2. Perfecting the `.clinerules` to manage the handoff between the planner and implementer.
3. Hooking properly into Linear for task tracking and status updates using MCP.
4. Cleaning up redundant files from the repo and migrating internal knowledge to a `docs/features/` setup.
5. Standardizing the CI/Validation workflow via your agent scripts.

You can find the prompt in the artifact below. Simply copy the contents of this artifact and start a new conversation with Claude Opus to kick off the overhaul!

[claude_prompt.md](file:///home/felipe/.gemini/antigravity-ide/brain/befaa6bc-5e91-4864-8760-015ef4a0dce4/claude_prompt.md)

Let me know if you need any adjustments to the prompt or if you'd like me to start executing any of these cleanups for you!

---

### 👤 User (22:03:47)

Now give me another prompt, this time to analyze the existing features to check how they were implemented, how they work and document everything according to
@[/wsl+ubuntu/home/felipe/workfolder/imoveis/docs/features/_template.md]  . Also to verify if there are any bugs or possible issues in the existing implementations. Consider that this will be a brand new agent, so I'll need the required context again

<ADDITIONAL_METADATA>
The current local time is: 2026-07-20T19:03:47-03:00.

The user's current state is as follows:
Active Document: /home/felipe/workfolder/imoveis/docs/features/_template.md (LANGUAGE_MARKDOWN)
Cursor is on line: 1
Other open documents:
- /home/felipe/workfolder/imoveis/.clinerules/rules.md (LANGUAGE_MARKDOWN)
- /home/felipe/workfolder/imoveis/docs/adr/0001-dual-model-development.md (LANGUAGE_MARKDOWN)
- /home/felipe/workfolder/imoveis/mkdocs.yml (LANGUAGE_YAML)
- /home/felipe/workfolder/imoveis/.clinerules/python-backend.md (LANGUAGE_MARKDOWN)
- /home/felipe/workfolder/imoveis/docs/features/_template.md (LANGUAGE_MARKDOWN)

The user has mentioned some items in the form @[ITEM]. Here is extra information about the items that were mentioned by the user, in the order that they appear:

@[/wsl+ubuntu/home/felipe/workfolder/imoveis/docs/features/_template.md] is a [File]:
/wsl+ubuntu/home/felipe/workfolder/imoveis/docs/features/_template.md
</ADDITIONAL_METADATA>

---

### 👤 Assistant (22:04:02)

I have created the second prompt for you!

This prompt instructs Claude Opus to thoroughly scan your `src/` and `frontend/` directories, reverse-engineer the features that are already implemented, and evaluate them for bugs, race conditions, and architecture anti-patterns. Crucially, it instructs Claude to output its findings as markdown files in `docs/features/` matching your `_template.md` perfectly.

You can grab the prompt from the artifact below and paste it into a new agent session:

[feature_analysis_prompt.md](file:///home/felipe/.gemini/antigravity-ide/brain/befaa6bc-5e91-4864-8760-015ef4a0dce4/feature_analysis_prompt.md)

Let me know if there's any other context or specific focus areas you'd like me to add!

---
