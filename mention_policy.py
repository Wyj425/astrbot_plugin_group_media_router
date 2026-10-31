"""Scoped reply eligibility, independent of nicknames and probability selection."""

def requires_mention(rules, group_id, user_id):
    target = (str(group_id), str(user_id))
    for rule in rules or []:
        if not isinstance(rule, str):
            continue
        parts = tuple(part.strip() for part in rule.split(':'))
        if len(parts) == 2 and parts == target:
            return True
    return False


def mentions_bot(segments, bot_id):
    if not isinstance(segments, list) or not str(bot_id):
        return False
    for segment in segments:
        if not isinstance(segment, dict) or segment.get('type') != 'at':
            continue
        data = segment.get('data')
        if isinstance(data, dict) and str(data.get('qq', '')) == str(bot_id):
            return True
    return False
