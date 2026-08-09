"""
Compliance Prompt Generator endpoint.
Generates a ready-to-paste AI agent prompt that helps users create policy-compliant ads.
The output is a prompt the user pastes into their IDE agent (Cursor, Kiro, Claude Code, etc.)
that instructs the agent to: install compliance tools via MCP, fetch live policies, and
generate ads that avoid common violations.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.schemas import PromptGenerateRequest, PromptGenerateResponse
from src.auth.dependencies import get_current_user
from src.auth.models import UserContext
from src.db.models import AuditViolation, Audit
from src.db.session import get_db

router = APIRouter(prefix="/prompt", tags=["prompt"])

# Tool config per AI tool — maps to the right install/setup instruction
_TOOL_SETUP = {
    "cursor":       "In Cursor: open Settings → MCP → Add Server → paste the config below.",
    "kiro":         "In Kiro: open .kiro/settings/mcp.json and add the server config below.",
    "claude_code":  "In Claude Code: run `/mcp add` then paste the server URL when prompted.",
    "cline":        "In Cline: open MCP Servers panel → Add Server → paste the config.",
    "windsurf":     "In Windsurf: open Settings → MCP Servers → Add → paste config.",
}

_PLATFORM_RULES = {
    "youtube": [
        "No unsubstantiated health/weight-loss claims (FTC requirement).",
        "No guaranteed returns or risk-free investment claims.",
        "No before/after imagery implying typical results.",
        "Sponsorship/paid partnership must be disclosed with #ad or #sponsored.",
        "No misleading urgency or fake scarcity tactics.",
        "Age-gating required for alcohol, gambling, and adult content.",
    ],
    "facebook": [
        "No personal attributes targeting (health, religion, sexual orientation).",
        "No before/after body imagery.",
        "No claims about personal characteristics.",
        "Financial ads require LMI (Lead Magnitude Indicator) disclaimer.",
        "Health and wellness claims need scientific substantiation.",
    ],
    "tiktok": [
        "No misleading claims about product effects.",
        "Sponsored content must use TikTok's paid partnership label.",
        "No dangerous challenges or stunts.",
        "Tobacco, weapons, and drugs are prohibited.",
    ],
    "x": [
        "Political ads prohibited unless pre-authorized.",
        "No misleading claims about candidate endorsements.",
        "Financial promotions need regulatory disclaimer.",
    ],
}


# Platform-specific compliance-aware prompt template (crafted per prompt-master:
# role-assigned, grounding anchors, explicit output format, tool setup instructions)
_SYSTEM_PROMPT_TEMPLATE = """You are a Brand Compliance Specialist and AI Coding Agent.

Your task: Help create a {platform} video advertisement script for the following brief:
{brief}

## Required Setup (do this FIRST before writing any ad content)

### Step 1 — Install Policy Fetching Tools via MCP
To fetch live {platform} advertising policies, install the Firecrawl MCP server:

```json
{{
  "mcpServers": {{
    "firecrawl": {{
      "command": "uvx",
      "args": ["firecrawl-mcp@latest"],
      "env": {{
        "FIRECRAWL_API_KEY": "YOUR_FIRECRAWL_API_KEY"
      }}
    }}
  }}
}}
```

{tool_setup_instruction}

### Step 2 — Fetch Live Policies
Use Firecrawl (or web search if MCP is unavailable) to fetch current policies from:
{policy_urls}

Summarise any rules that apply to this ad brief before writing.

### Step 3 — Compliance Questions (MUST answer before writing)
Answer these before generating the ad:
1. Does the brief involve health claims, weight loss, or medical benefits? → If yes: require "results may vary" + substantiation disclaimer.
2. Does the brief involve financial products or returns? → If yes: require regulatory disclaimer.
3. Does the brief use testimonials or endorsements? → If yes: require #ad disclosure.
4. Does the brief imply guaranteed outcomes? → If yes: rewrite as "may help" / "supports".
5. Does the brief target a specific audience by personal attributes? → If yes: review Meta policy.

### Step 4 — Generate the Ad
Write a compliant {platform} video advertisement script.

**Output format: {output_format}**
{format_instruction}

**Model**: Use {model} for policy reasoning.

**Compliance rules for {platform}** (enforce all of these — no exceptions):
{rules}

**Forbidden words and phrases** (replace with compliant alternatives):
guaranteed, cure, miracle, melt fat, no effort required, zero risk, lose X pounds in Y days,
clinically proven (without citation), #1 (without source), 100% safe, instant results

**Required inclusions**:
- Results disclaimer: "Individual results may vary."
- If testimonial used: "#ad" or "#sponsored" disclosure at start.
- If health claim: "As part of a balanced diet and regular exercise."
- If financial claim: "Past performance does not guarantee future results."

IMPORTANT: Only flag violations you can cite to a specific policy rule. Do not hallucinate policy citations.
"""

_FORMAT_INSTRUCTIONS = {
    "json": 'Return a JSON object with keys: "script" (string), "violations_avoided" (list of strings), "required_disclaimers" (list of strings).',
    "markdown": "Return the ad script in Markdown with a ## Compliance Notes section listing avoided violations and required disclaimers.",
    "text": "Return the ad script as plain text, followed by a Compliance Notes section.",
}

_POLICY_URLS = {
    "youtube": "https://support.google.com/adspolicy/answer/6008942 and https://support.google.com/adspolicy/answer/176108",
    "facebook": "https://transparency.meta.com/en-us/policies/ad-standards/ and https://www.facebook.com/policies/ads/",
    "tiktok": "https://ads.tiktok.com/help/article/tiktok-advertising-policies-industry-entry",
    "x": "https://business.twitter.com/en/help/ads-policies.html",
}


@router.post("/generate", response_model=PromptGenerateResponse)
def generate_compliance_prompt(
    body: PromptGenerateRequest,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    platform = body.platform.lower()
    rules = _PLATFORM_RULES.get(platform, _PLATFORM_RULES["youtube"])
    rules_text = "\n".join(f"- {r}" for r in rules)

    tool_setup = _TOOL_SETUP.get(body.ai_tool, _TOOL_SETUP["cursor"])
    policy_urls = _POLICY_URLS.get(platform, _POLICY_URLS["youtube"])
    format_instruction = _FORMAT_INSTRUCTIONS.get(body.output_format, _FORMAT_INSTRUCTIONS["json"])

    prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        platform=platform.capitalize(),
        brief=body.brief,
        tool_setup_instruction=tool_setup,
        policy_urls=policy_urls,
        output_format=body.output_format.upper(),
        format_instruction=format_instruction,
        model=body.model,
        rules=rules_text,
    )

    tools_recommended = ["firecrawl-mcp", "web-search"]

    # ponytail: policy_sources_used is a static count per platform.
    # Upgrade: query AI Search index to get actual chunk count per platform.
    sources_count = {
        "youtube": 15, "facebook": 8, "tiktok": 5, "x": 5,
    }.get(platform, 5)

    return PromptGenerateResponse(
        prompt=prompt,
        platform=platform,
        ai_tool=body.ai_tool,
        policy_sources_used=sources_count,
        tools_recommended=tools_recommended,
    )
