# Message Format Design Brief
## AI News Bot | WhatsApp Channel Automation

**Version:** 1.0  
**Status:** Locked — Do Not Change Without Explicit Approval

---

## 1. Primary Message Template (Full LLM Summary)

This is the locked format for all posts where LLM summarization succeeds.

```
📰 *[HEADLINE IN ALL CAPS — MAX 15 WORDS]*

📋 *Summary:*
[Paragraph 1 — 2-3 sentences. What happened, who is involved, what led to this. 
Write at 8th grade reading level. No technical jargon unless essential to the story. 
Each paragraph should read as approximately 6-7 lines on a mobile screen.]

[Paragraph 2 — 2-3 sentences. Why this matters, who is affected, scale of impact. 
Include specific numbers, percentages, or user counts if available in the article. 
If no numbers available, describe scope qualitatively.]

[Paragraph 3 — 2-3 sentences. Broader context, industry reactions, what comes 
next. Forward-looking. What should readers watch for.]

*🔑 What Actually Happened:*
- [Point 1 — The exact event, one sharp declarative sentence]
- [Point 2 — How it happened: mechanism, trigger, or decision that caused this]
- [Point 3 — Who is directly affected: company, users, developers, or market]
- [Point 4 — Scale or numbers: quantify if possible, omit this point if no data]
- [Point 5 — Key quote or reaction: attribute to role not name e.g. "Anthropic CEO" not "Dario"]

*💡 Conclusion:*
[1-2 sentences maximum. The so-what. Why does this matter to the AI industry? 
What shifts because of this event? Make it punchy and memorable.]
```

---

## 2. Real Example — Locked Format Applied

Based on the Anthropic/India article provided:

```
📰 *AS ANTHROPIC SUSPENDS ACCESS TO NEW MODELS, INDIA DEBATES ITS AI FUTURE*

📋 *Summary:*
Anthropic suspended access to its newest AI models — Fable 5 and Mythos 5 — 
following a U.S. government directive, citing national security concerns. The 
move blindsided the global tech community, coming just days after Anthropic 
announced a major partnership with Indian IT giant Tata Consultancy Services.

The suspension raised immediate alarms in India, one of the world's largest 
AI markets and Anthropic's second-biggest market after the U.S. Indian startups 
with cross-border teams suddenly faced an unequal playing field — developers 
outside the U.S. lost access to frontier models their American counterparts 
could still use freely.

The episode triggered a national debate about India's dangerous dependence on 
U.S. AI infrastructure. Industry leaders, investors, and policymakers called 
for accelerating domestic AI development, with some proposing a ₹500 billion 
annual fund to build sovereign AI capabilities.

*🔑 What Actually Happened:*
- The U.S. government ordered Anthropic to suspend access to Fable 5 and Mythos 5 for all foreign nationals
- Security concerns were reportedly first flagged to the government by Amazon CEO Andy Jassy
- Indian developers, startups, and Anthropic's own foreign national employees lost access
- India represents Anthropic's second-largest global market — the stakes are significant
- Zoho founder Sridhar Vembu urged Indian companies to "embrace smaller models, both Indian and Chinese open source ones"

*💡 Conclusion:*
This is the clearest proof yet that American AI models carry American geopolitical risk — 
and any country that built its AI strategy on a single foreign provider just learned 
that lesson the hard way.
```

---

## 3. Fallback Template (Raw RSS — No LLM)

Used when all LLM providers fail. Post is still sent — never skipped.

```
📰 *[HEADLINE IN ALL CAPS]*

📋 *Summary:*
[Raw RSS description text — HTML tags stripped, line breaks normalized. 
If RSS description is longer than 800 characters, truncate at last complete 
sentence before the 800-character mark and append "..."]

*💡 Conclusion:*
[Static text: "This is a developing story. Stay tuned for full analysis."]
```

---

## 4. WhatsApp Formatting Rules

### 4.1 WhatsApp Markdown Reference

| Effect | Syntax | Example |
|--------|--------|---------|
| Bold | `*text*` | `*HEADLINE*` |
| Italic | `_text_` | `_source_` |
| Strikethrough | `~text~` | Not used |
| Monospace | ` ```text``` ` | Not used |
| Bullet | `- text` | `- Point 1` |
| Line break | `\n` | Between paragraphs |

### 4.2 Character Budget

| Element | Max Characters | Notes |
|---------|---------------|-------|
| WhatsApp image caption | 4,096 | Hard platform limit |
| Headline | ~80 chars | ~15 words max in CAPS |
| Paragraph 1 | ~400 chars | 2-3 sentences |
| Paragraph 2 | ~400 chars | 2-3 sentences |
| Paragraph 3 | ~400 chars | 2-3 sentences |
| 5 bullet points | ~600 chars total | ~120 chars each |
| Conclusion | ~200 chars | 1-2 sentences |
| Formatting symbols (emojis, labels) | ~150 chars | Fixed overhead |
| **Total target** | **~2,200 chars** | Well within 4,096 limit |

### 4.3 Mobile Readability Rules

- **Paragraph length:** Each paragraph should be 3-4 sentences when displayed on mobile (≈ 6-7 lines at standard font size)
- **Sentence length:** Max 25 words per sentence — shorter reads better on mobile
- **Blank lines:** One blank line between every section for visual breathing room
- **No URLs in text:** Never include article links anywhere in the post
- **No source attribution:** Never mention the publication name (TechCrunch, Verge, etc.)
- **No hashtags:** WhatsApp Channels don't benefit from hashtag discovery
- **CAPS headlines only:** Do not use title case in headlines — ALL CAPS is intentional for visual hierarchy

---

## 5. LLM System Prompt

This exact prompt is sent to all LLM providers. Do not change it between providers — consistency is required.

```
You are a tech news editor writing structured summaries for a WhatsApp channel 
of AI practitioners, developers, and startup founders.

Your audience reads on mobile. They are busy and highly technical. They want 
facts, context, and implications — not marketing language or hype.

Given this article:
TITLE: {title}
CONTENT: {content}

Write a structured summary using EXACTLY this output format (no other text, 
no preamble, no "Here is the summary:"):

HEADLINE: {ALL CAPS version of the headline, max 15 words, no punctuation at end}

PARAGRAPH_1: {2-3 sentences. What happened, who is involved, what led to this. 
8th grade reading level. No jargon.}

PARAGRAPH_2: {2-3 sentences. Why this matters, who is affected, scale of impact. 
Include numbers if available.}

PARAGRAPH_3: {2-3 sentences. Broader context, reactions, what comes next.}

POINT_1: {The exact event — one declarative sentence}
POINT_2: {How it happened — the mechanism or trigger}
POINT_3: {Who is affected — specific actors}
POINT_4: {Scale or numbers — if unavailable, write "N/A"}
POINT_5: {Key quote or reaction — attribute to role not name}

CONCLUSION: {1-2 sentences. The so-what for the AI world.}

STRICT RULES:
- Output ONLY the labeled fields above. Nothing else.
- No hashtags anywhere
- No source names (no "TechCrunch", "The Verge", etc.)
- No URLs
- No "Read more" or "Source:" lines
- No marketing language ("revolutionary", "game-changing", "unprecedented")
- If numbers are not in the article, do not invent them
- If POINT_4 has no data, write: "Scale not yet disclosed"
- Attribute quotes to role: "Anthropic CEO" not "Dario Amodei"
```

---

## 6. LLM Response Parser

The LLM response must be parsed into a `SummaryResult` object. Use this parsing logic:

```python
def parse_llm_response(response_text: str) -> SummaryResult:
    """
    Parse labeled LLM output into SummaryResult.
    Handles minor formatting variations gracefully.
    """
    fields = {
        'HEADLINE': '',
        'PARAGRAPH_1': '',
        'PARAGRAPH_2': '',
        'PARAGRAPH_3': '',
        'POINT_1': '',
        'POINT_2': '',
        'POINT_3': '',
        'POINT_4': '',
        'POINT_5': '',
        'CONCLUSION': ''
    }
    
    current_field = None
    current_lines = []
    
    for line in response_text.strip().split('\n'):
        stripped = line.strip()
        matched = False
        for field in fields:
            if stripped.startswith(f'{field}:'):
                if current_field:
                    fields[current_field] = ' '.join(current_lines).strip()
                current_field = field
                value_part = stripped[len(field)+1:].strip()
                current_lines = [value_part] if value_part else []
                matched = True
                break
        if not matched and current_field and stripped:
            current_lines.append(stripped)
    
    if current_field:
        fields[current_field] = ' '.join(current_lines).strip()
    
    # Validation: require at minimum HEADLINE and PARAGRAPH_1
    if not fields['HEADLINE'] or not fields['PARAGRAPH_1']:
        raise ValueError(f"LLM response missing required fields: {response_text[:200]}")
    
    return SummaryResult(
        headline=fields['HEADLINE'].upper(),
        paragraph_1=fields['PARAGRAPH_1'],
        paragraph_2=fields['PARAGRAPH_2'],
        paragraph_3=fields['PARAGRAPH_3'],
        point_1=fields['POINT_1'],
        point_2=fields['POINT_2'],
        point_3=fields['POINT_3'],
        point_4=fields['POINT_4'] if fields['POINT_4'] not in ('N/A', '') else None,
        point_5=fields['POINT_5'],
        conclusion=fields['CONCLUSION']
    )
```

---

## 7. Message Builder

```python
def build_message(summary: SummaryResult) -> str:
    """
    Assemble the locked WhatsApp message template from a SummaryResult.
    """
    parts = []
    
    # Headline
    parts.append(f"📰 *{summary.headline}*")
    parts.append("")
    
    # Summary section
    parts.append("📋 *Summary:*")
    parts.append(summary.paragraph_1)
    parts.append("")
    
    if summary.paragraph_2:
        parts.append(summary.paragraph_2)
        parts.append("")
    
    if summary.paragraph_3:
        parts.append(summary.paragraph_3)
        parts.append("")
    
    # Bullet points
    parts.append("*🔑 What Actually Happened:*")
    for point in [summary.point_1, summary.point_2, summary.point_3, 
                  summary.point_4, summary.point_5]:
        if point and point not in ('N/A', 'None', ''):
            parts.append(f"- {point}")
    parts.append("")
    
    # Conclusion
    parts.append("*💡 Conclusion:*")
    parts.append(summary.conclusion)
    
    message = "\n".join(parts)
    
    # Hard cap at 4096 chars (WhatsApp limit)
    if len(message) > 4096:
        # Truncate conclusion to fit
        overhead = len(message) - 4096
        truncated_conclusion = summary.conclusion[:len(summary.conclusion) - overhead - 3] + "..."
        parts[-1] = truncated_conclusion
        message = "\n".join(parts)
    
    return message


def build_fallback_message(article) -> str:
    """
    Raw RSS fallback — used when all LLMs fail.
    """
    # Strip HTML tags from description
    from bs4 import BeautifulSoup
    clean_desc = BeautifulSoup(article.description, 'lxml').get_text()
    
    # Truncate at 800 chars
    if len(clean_desc) > 800:
        clean_desc = clean_desc[:800].rsplit('.', 1)[0] + "..."
    
    headline = article.title.upper()
    
    return (
        f"📰 *{headline}*\n\n"
        f"📋 *Summary:*\n"
        f"{clean_desc}\n\n"
        f"*💡 Conclusion:*\n"
        f"This is a developing story. Stay tuned for full analysis."
    )
```

---

## 8. Quality Checklist (Pre-Send Validation)

Before Baileys sends, the Python formatter validates:

| Check | Pass Condition | Fail Action |
|-------|---------------|-------------|
| Message not empty | len(message) > 100 | Use fallback template |
| Headline present | message starts with 📰 | Re-format with raw title |
| Within length limit | len(message) <= 4096 | Truncate conclusion |
| No URLs in message | `http` not in message | Strip any URLs that snuck in |
| No source names | Source not in message | Strip source name if present |
| No hashtags | `#` not in message | Strip all hashtags |
| Has conclusion | `💡` in message | Append static conclusion |

---
