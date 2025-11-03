from typing import Dict, Any, List

def _detect_rolling(deadlines: Dict[str, Any]) -> bool:
    if not isinstance(deadlines, dict):
        return False
    return bool(deadlines.get('rolling'))

def _detect_test_label(test_policy: Dict[str, Any]) -> str:
    if not isinstance(test_policy, dict):
        return ""
    policy_type = (test_policy.get('type') or '').lower()
    if 'optional' in policy_type:
        return 'Test-Optional'
    if 'blind' in policy_type:
        return 'Test-Blind'
    return ''

def to_json_with_labels(requirement: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(requirement)
    result['labels'] = {
        'rolling_admission': _detect_rolling(requirement.get('deadlines') or {}),
        'test_label': _detect_test_label(requirement.get('test_policy') or {})
    }
    return result

def to_markdown(requirement: Dict[str, Any]) -> str:
    university = requirement.get('university', '')
    program = requirement.get('program', '')
    deadlines = requirement.get('deadlines') or {}
    documents: List[Dict[str, Any]] = requirement.get('required_documents') or []
    essays: List[Dict[str, Any]] = requirement.get('essay_prompts') or []
    portfolio_required = requirement.get('portfolio_required', False)
    interview = requirement.get('interview') or {}
    fee_info = requirement.get('fee_info') or {}
    test_policy = requirement.get('test_policy') or {}

    rolling = _detect_rolling(deadlines)
    test_label = _detect_test_label(test_policy)

    lines: List[str] = []
    lines.append(f"## Application Checklist: {university} — {program}")
    if rolling:
        lines.append("- Label: Rolling Admission")
    if test_label:
        lines.append(f"- Label: {test_label}")
    lines.append("")
    lines.append("### Deadlines")
    for key in ['early_decision', 'early_action', 'regular_decision', 'priority']:
        if deadlines.get(key):
            pretty = key.replace('_', ' ').title()
            lines.append(f"- {pretty}: {deadlines.get(key)}")
    if deadlines.get('rolling'):
        lines.append("- Rolling: Yes")

    lines.append("")
    lines.append("### Required Documents")
    if not documents:
        lines.append("- (none listed)")
    for d in documents:
        name = d.get('name')
        req = 'Required' if d.get('required') else 'Optional'
        lines.append(f"- {name} ({req})")
        if d.get('details'):
            lines.append(f"  - Details: {d.get('details')}")

    lines.append("")
    lines.append("### Essay Prompts")
    if not essays:
        lines.append("- (none listed)")
    for e in essays:
        lines.append(f"- {e.get('type', '')}")
        if e.get('prompt'):
            lines.append(f"  - Prompt: {e.get('prompt')}")
        if e.get('word_limit'):
            lines.append(f"  - Word Limit: {e.get('word_limit')}")

    lines.append("")
    lines.append("### Portfolio")
    lines.append(f"- Required: {'Yes' if portfolio_required else 'No'}")

    if interview.get('policy'):
        lines.append("")
        lines.append("### Interview")
        lines.append(f"- Policy: {interview.get('policy')}")

    lines.append("")
    lines.append("### Fees")
    if fee_info.get('amount'):
        lines.append(f"- Amount: {fee_info.get('amount')} {fee_info.get('currency', '')}")
    lines.append(f"- Fee Waiver Available: {'Yes' if fee_info.get('waiver_available') else 'No'}")
    if fee_info.get('waiver_details'):
        lines.append(f"- Waiver Details: {fee_info.get('waiver_details')}")

    if requirement.get('is_ambiguous'):
        lines.append("")
        lines.append("### Ambiguity")
        lines.append(requirement.get('ambiguity_details') or '')

    return "\n".join(lines)


